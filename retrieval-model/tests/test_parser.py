import unittest
from charaka_backend.parser import normalize, parse_chapter

class ParserTests(unittest.TestCase):
    def test_devanagari_normalization_preserves_vowel_signs(self):
        self.assertEqual(normalize("ज्वर"), "ज्वर")
        self.assertEqual(normalize("तृष्णा"), "तृष्णा")

    def test_extracts_sanskrit_transliteration_and_translation(self):
        doc = {
            "source": "Charaka Samhita", "chapter": "Test Adhyaya",
            "url": "https://example.org",
            "content": [
                {"type": "h1", "text": "Test Adhyaya", "level": 1},
                {"type": "h2", "text": "Sanskrit text, Transliteration and English Translation", "level": 2},
                {"type": "h3", "text": "Jwara symptoms", "level": 3},
                {"type": "p", "text": "ज्वरो विकारो रोगश्च||१||"},
                {"type": "p", "text": "jvarō vikārō rōgaśca||1||"},
                {"type": "p", "text": "Jwara is associated with fever and body discomfort."}
            ]
        }
        rows = parse_chapter(doc, "Nidana Sthana/01 Jwara Nidana/Jwara_Nidana.json")
        verse = next(x for x in rows if x["shloka"])
        self.assertEqual(verse["sthana"], "Nidana Sthana")
        self.assertIn("ज्वरो", verse["shloka"])
        self.assertIn("jvarō", verse["transliteration"])
        self.assertIn("fever", verse["translation"])

    def test_tables_are_flattened_for_search(self):
        doc = {
            "chapter": "Table Chapter",
            "content": [
                {"type": "h1", "text": "Table Chapter", "level": 1},
                {"type": "table", "rows": [[{"type": "th", "text": "Symptom"}, {"type": "td", "text": "Thirst"}]]}
            ]
        }
        rows = parse_chapter(doc, "Sutra Sthana/01 Test/Test.json")
        self.assertTrue(any("Thirst" in x["search_text"] for x in rows))

if __name__ == "__main__":
    unittest.main()
