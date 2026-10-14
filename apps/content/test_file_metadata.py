import io
import shutil
import tempfile
import zipfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.api.serializers import ResourceSerializer
from apps.content.file_metadata import get_file_metadata
from apps.content.models import Resource


def make_pdf(pages):
    import pypdfium2

    document = pypdfium2.PdfDocument.new()
    for _ in range(pages):
        document.new_page(200, 200)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def make_office_zip(app_xml=None, extra_entries=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        if app_xml is not None:
            archive.writestr('docProps/app.xml', app_xml)
        for entry in extra_entries:
            archive.writestr(entry, '<x/>')
    return buffer.getvalue()


APP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    '{body}</Properties>'
)


class FileMetadataHelperTests(SimpleTestCase):
    def metadata(self, content, name):
        return get_file_metadata(io.BytesIO(content), name)

    def test_pdf_page_count(self):
        content = make_pdf(3)
        self.assertEqual(self.metadata(content, 'notes.PDF'), (len(content), 3))

    def test_docx_pages_from_app_xml(self):
        content = make_office_zip(APP_XML.format(body='<Pages>12</Pages><Words>900</Words>'))
        self.assertEqual(self.metadata(content, 'notes.docx'), (len(content), 12))

    def test_pptx_slides_from_app_xml(self):
        content = make_office_zip(APP_XML.format(body='<Slides>7</Slides>'))
        self.assertEqual(self.metadata(content, 'deck.pptx')[1], 7)

    def test_pptx_falls_back_to_slide_entries(self):
        content = make_office_zip(extra_entries=[
            'ppt/slides/slide1.xml', 'ppt/slides/slide2.xml',
            'ppt/slides/_rels/slide1.xml.rels', 'ppt/slideLayouts/slideLayout1.xml',
        ])
        self.assertEqual(self.metadata(content, 'deck.pptx')[1], 2)

    def test_docx_without_app_xml_has_no_page_count(self):
        content = make_office_zip()
        self.assertEqual(self.metadata(content, 'notes.docx'), (len(content), None))

    def test_other_types_have_size_only(self):
        for name in ['photo.png', 'data.csv', 'readme.txt', 'sheet.xlsx', 'legacy.doc', 'noext']:
            with self.subTest(name=name):
                self.assertEqual(self.metadata(b'abcde', name), (5, None))

    def test_corrupt_files_never_raise(self):
        with self.assertLogs('apps.content.file_metadata', level='WARNING'):
            self.assertEqual(self.metadata(b'%PDF-1.4 broken', 'bad.pdf'), (15, None))
        with self.assertLogs('apps.content.file_metadata', level='WARNING'):
            self.assertEqual(self.metadata(b'not a zip', 'bad.docx'), (9, None))

    def test_rewinds_file(self):
        handle = io.BytesIO(make_pdf(1))
        get_file_metadata(handle, 'a.pdf')
        self.assertEqual(handle.tell(), 0)


class ResourceMetadataTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def create_resource(self, content, name='notes.pdf', **extra):
        return Resource.objects.create(
            title='Notes',
            file=SimpleUploadedFile(name, content),
            file_type=Resource.TYPE_LECTURE_NOTE,
            status=Resource.STATUS_PUBLISHED,
            **extra,
        )

    def test_metadata_filled_on_upload(self):
        content = make_pdf(2)
        resource = self.create_resource(content)
        resource.refresh_from_db()
        self.assertEqual((resource.file_size, resource.page_count), (len(content), 2))
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), content)

    def test_unrelated_save_does_not_reread_file(self):
        resource = Resource.objects.get(pk=self.create_resource(make_pdf(1)).pk)
        with patch('apps.content.file_metadata.get_file_metadata') as metadata:
            resource.title = 'Renamed'
            resource.save()
            resource.save(update_fields=['title'])
        metadata.assert_not_called()

    def test_changing_file_recomputes_with_update_fields(self):
        resource = Resource.objects.get(pk=self.create_resource(make_pdf(1)).pk)
        content = make_pdf(4)
        resource.file.save('other.pdf', io.BytesIO(content), save=False)
        resource.save(update_fields=['file'])
        resource.refresh_from_db()
        self.assertEqual((resource.file_size, resource.page_count), (len(content), 4))

    def test_unreadable_file_does_not_block_upload(self):
        with patch('apps.content.file_metadata.get_file_metadata', side_effect=RuntimeError('boom')):
            resource = self.create_resource(b'data')
        resource.refresh_from_db()
        self.assertTrue(resource.file.name)
        self.assertIsNone(resource.file_size)

    def test_backfill_command_fills_missing_and_tolerates_missing_files(self):
        content = make_pdf(3)
        present = self.create_resource(content)
        absent = self.create_resource(b'gone', name='gone.pdf')
        Resource.objects.update(file_size=None, page_count=None)
        absent.file.storage.delete(absent.file.name)

        out = io.StringIO()
        call_command('backfill_resource_metadata', stdout=out)
        present.refresh_from_db()
        self.assertEqual((present.file_size, present.page_count), (len(content), 3))
        self.assertIn('updated=1', out.getvalue())
        self.assertIn('missing_file=1', out.getvalue())

        out = io.StringIO()
        call_command('backfill_resource_metadata', '--force', stdout=out)
        self.assertIn('checked=2', out.getvalue())

    def test_serializer_exposes_metadata_fields(self):
        content = make_pdf(2)
        resource = self.create_resource(content, name='Notes.PDF', original_caption='  Week 1 notes \n')
        data = ResourceSerializer(resource).data
        self.assertEqual(data['file_size'], len(content))
        self.assertEqual(data['page_count'], 2)
        self.assertEqual(data['file_extension'], 'pdf')
        self.assertEqual(data['description'], 'Week 1 notes')
        for field in ['id', 'title', 'file_type', 'course_codes', 'file_url', 'file_url_expires_in']:
            self.assertIn(field, data)

    def test_serializer_nulls_for_empty_caption_and_no_extension(self):
        resource = self.create_resource(b'plain', name='README')
        data = ResourceSerializer(resource).data
        self.assertIsNone(data['description'])
        self.assertIsNone(data['file_extension'])
        self.assertIsNone(data['page_count'])
        self.assertEqual(data['file_size'], 5)
