"""Regression tests use synthetic captions and a generated 4:3 PNG only."""
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sync', ROOT / 'skills/slide-transcript-sync/scripts/sync.py')
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def png(path, width=800, height=600):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    rows = b''.join(b'\0' + bytes([38 + (y // 50) % 2 * 25, 84, 67]) * width for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    png(root / 'page.png')
    sync.write_json(root / 'captions.json', [
        {'start': 0, 'end': 9, 'text': '这是合成测试课程，不是实际讲稿。'},
        {'start': 9, 'end': 12, 'text': '跨过边界的句子保持完整。'},
        {'start': 12, 'end': 16, 'text': 'Entropy 与信息熵可以同时检索。'},
        {'start': 20, 'end': 30, 'text': '返回旧页面。 </script><script>alert(1)</script>'},
    ])
    config = {
        'courseTitle': '信息论示例', 'lectureLabel': '演示课', 'title': '信息与不确定性',
        'duration': 30, 'sourceMode': 'pdf', 'captions': 'captions.json',
        'transcriptLanguage': 'zh-CN', 'transcriptLabel': '中文讲稿', 'captionSource': '合成测试',
        'chapters': [{'id': 'intro', 'title': '信息', 'firstSlide': 's01'}, {'id': 'entropy', 'title': '信息熵', 'firstSlide': 's02'}],
        'slides': [
            {'id': 's01', 'title': '信息', 'image': 'page.png', 'sourcePage': 1, 'start': 0, 'chapter': 'intro'},
            {'id': 'extra', 'title': '无独立讲稿的图片', 'image': 'page.png', 'sourcePage': 2, 'start': None, 'chapter': 'intro', 'confidence': 'unmatched'},
            {'id': 's02', 'title': '信息熵 Entropy', 'image': 'page.png', 'sourcePage': 3, 'start': 10, 'chapter': 'entropy'},
            {'id': 's03', 'title': '回看信息', 'image': 'page.png', 'sourcePage': 1, 'start': 20, 'chapter': 'entropy'},
        ]}
    sync.write_json(root / 'config.json', config)
    return config


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        return sync.build(self.root / 'config.json', self.root / 'reader', True)

    def test_srt_vtt_unicode_and_txt(self):
        for name, text in [('a.srt', '1\n00:00:00,000 --> 00:00:04,200\n你好 world\n\n2\n00:00:04,200 --> 00:00:09,000\n第二句'),
                           ('a.vtt', 'WEBVTT\n\n00:00.000 --> 00:04.200 align:start\n<v Teacher>你好 &amp; world</v>\n\n00:04.200 --> 00:09.000\n第二句')]:
            path = self.root / name
            path.write_text(text, encoding='utf-8')
            cues = sync.parse_captions(path, 9)['segments']
            self.assertEqual(len(cues), 2)
            self.assertEqual(cues[0]['end'], 4.2)
            self.assertIn('你好', cues[0]['text'])
            self.assertNotIn('<v', cues[0]['text'])
        path = self.root / 'a.txt'
        path.write_text('[00:00] 你好\nworld\n00:04\n第二句', encoding='utf-8')
        with self.assertRaises(ValueError):
            sync.parse_captions(path)
        data = sync.parse_captions(path, 9)
        self.assertEqual(data['segments'][0]['text'], '你好 world')
        self.assertEqual(data['segments'][-1]['end'], 9)
        self.assertEqual(data['timing'], 'end-times-inferred')

    def test_complete_assignment_unmatched_revisit_and_zip(self):
        result = self.build()
        self.assertTrue(result['externalCaptionComparison'])
        self.assertEqual(result['cues'], 4)
        data = sync.read_json(self.root / 'reader/lecture-data.json')
        self.assertEqual(data['slides'][0]['paragraphs'][0]['cueIds'], [1, 2])
        self.assertEqual(data['slides'][1]['paragraphs'], [])
        self.assertEqual(data['slides'][3]['sourcePage'], 1)
        self.assertNotIn(str(self.root), json.dumps(data))
        with zipfile.ZipFile(self.root / 'reader.zip') as z:
            self.assertIsNone(z.testzip())
            self.assertIn('reader/rebuild.py', z.namelist())
            self.assertEqual(len([n for n in z.namelist() if '/assets/' in n]), 4)

    def test_safe_embedding_and_portable_rebuild(self):
        self.build()
        site = self.root / 'reader'
        page = (site / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('</script><script>alert', page)
        self.assertIn('信息论示例', page)
        data = sync.read_json(site / 'lecture-data.json')
        data['title'] = '修改后的合成标题'
        sync.write_json(site / 'lecture-data.json', data)
        with self.assertRaises(ValueError):
            sync.verify(site)
        subprocess.run([sys.executable, str(site / 'rebuild.py')], cwd=self.root, check=True, capture_output=True)
        self.assertTrue(sync.verify(site, self.root / 'captions.json')['passed'])

    def test_tampered_text_duplicate_and_wrong_slide_fail(self):
        self.build()
        site = self.root / 'reader'
        original = sync.read_json(site / 'lecture-data.json')
        for change in ('text', 'duplicate', 'slide'):
            data = json.loads(json.dumps(original))
            if change == 'text':
                data['slides'][0]['paragraphs'][0]['text'] = '被篡改的文本'
            elif change == 'duplicate':
                data['slides'][0]['paragraphs'].append(data['slides'][0]['paragraphs'][0])
            else:
                data['slides'][2]['paragraphs'], data['slides'][3]['paragraphs'] = data['slides'][3]['paragraphs'], data['slides'][2]['paragraphs']
            sync.write_json(site / 'lecture-data.json', data)
            with self.assertRaises(ValueError):
                sync.verify(site)

    def test_invalid_times_ids_urls_and_missing_images_fail(self):
        for change in ('order', 'nan', 'duplicate', 'url', 'image'):
            config = json.loads(json.dumps(self.config))
            if change == 'order':
                config['slides'][2]['start'] = 0
            elif change == 'nan':
                config['duration'] = float('nan')
            elif change == 'duplicate':
                config['slides'][2]['id'] = 's01'
            elif change == 'url':
                config['sourceUrl'] = 'javascript:alert(1)'
            else:
                config['slides'][2]['image'] = 'absent.png'
            sync.write_json(self.root / 'config.json', config)
            with self.assertRaises(ValueError):
                self.build()

    def test_nonempty_output_is_preserved(self):
        site = self.root / 'reader'
        site.mkdir()
        (site / 'keep.txt').write_text('preserve', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.build()
        sync.build(self.root / 'config.json', site, True, True)
        self.assertEqual((site / 'keep.txt').read_text(), 'preserve')
        with zipfile.ZipFile(self.root / 'reader.zip') as z:
            self.assertNotIn('reader/keep.txt', z.namelist())

    def test_malformed_subtitles_fail_without_silent_loss(self):
        path = self.root / 'bad.srt'
        path.write_text('1\n00:00:00,000 --> 00:00:04,000\nValid\n\n2\nBAD --> 00:00:09,000\nMust not disappear', encoding='utf-8')
        with self.assertRaises(ValueError):
            sync.parse_captions(path, 9)

    def test_external_captions_detect_coordinated_tampering(self):
        self.build()
        site = self.root / 'reader'
        data = sync.read_json(site / 'lecture-data.json')
        old = data['cues'][0]['text']
        data['cues'][0]['text'] = 'changed'
        data['slides'][0]['paragraphs'][0]['text'] = data['slides'][0]['paragraphs'][0]['text'].replace(old, 'changed')
        sync.write_json(site / 'lecture-data.json', data)
        subprocess.run([sys.executable, str(site / 'rebuild.py')], check=True, capture_output=True)
        self.assertTrue(sync.verify(site)['passed'])
        with self.assertRaises(ValueError):
            sync.verify(site, self.root / 'captions.json')


if __name__ == '__main__':
    unittest.main()
