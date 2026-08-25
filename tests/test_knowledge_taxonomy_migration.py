import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_taxonomy_migration import (
        load_knowledge_taxonomy_migration,
    )
except ModuleNotFoundError:
    load_knowledge_taxonomy_migration = None


class KnowledgeTaxonomyMigrationTests(unittest.TestCase):
    def test_prefix_alias_maps_legacy_grammar_roots_to_teacher_taxonomy(self):
        self.assertTrue(
            callable(load_knowledge_taxonomy_migration),
            "load_knowledge_taxonomy_migration must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = Path(temp_dir) / "migration.json"
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": "knowledge-taxonomy-migration-v1",
                        "rules": [
                            {
                                "rule_id": "legacy-grammar-wording-to-morphology",
                                "source_prefix": "知识点->语法词法",
                                "target_prefix": "知识点->词法",
                            },
                            {
                                "rule_id": "legacy-grammar-syntax-to-syntax",
                                "source_prefix": "知识点->语法句法",
                                "target_prefix": "知识点->句法",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            migration = load_knowledge_taxonomy_migration(policy)

        mapped = migration.canonicalize("知识点->语法词法->代词->物主代词->形容词性物主代词")
        self.assertEqual(mapped.canonical_path, "知识点->词法->代词->物主代词->形容词性物主代词")
        self.assertEqual(mapped.status, "prefix_alias")
        self.assertEqual(mapped.rule_id, "legacy-grammar-wording-to-morphology")
        identity = migration.canonicalize("知识点->词汇->固定搭配/句型")
        self.assertEqual(identity.canonical_path, "知识点->词汇->固定搭配/句型")
        self.assertEqual(identity.status, "identity")


if __name__ == "__main__":
    unittest.main()
