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
    def test_teacher_migration_covers_three_explicit_renamed_labels(self):
        self.assertTrue(callable(load_knowledge_taxonomy_migration))
        policy = (
            Path(__file__).resolve().parents[1]
            / "configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json"
        )
        migration = load_knowledge_taxonomy_migration(policy)
        expected = {
            "知识点->词法->动词->情态动词->(don't/doesn't/didn't) have to":
                "知识点->词法->动词->情态动词->have to",
            "知识点->句法->句子种类->疑问句->特殊疑问句->how类特殊疑问句":
                "知识点->句法->句子种类->疑问句->特殊疑问句->how类特殊疑问词",
            "知识点->句法->句子种类->疑问句->特殊疑问句->wh-类特殊疑问句":
                "知识点->句法->句子种类->疑问句->特殊疑问句->wh-类特殊疑问词",
        }
        for legacy, canonical in expected.items():
            result = migration.canonicalize(legacy)
            self.assertEqual(result.canonical_path, canonical)
            self.assertEqual(result.status, "prefix_alias")

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
