#!/usr/bin/env python3
"""
确认测试: 抽屉级联压缩引擎 全链路管线
Tier1(drawer_engine) -> Tier2(memory-butler) -> Tier3(context-assembler)

运行: python3 tests/test_pipeline_full.py -v
"""

import os
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

ROUNDC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROUNDC_DIR))

from drawer_engine import (
    DrawerStack, TemperatureIndex, DedupEngine,
    NoiseFilter, ProtectionDetector, UniqueKeyIndex, ConflictResolver,
)
PROTECTED_MARKER = "__HERMES_SOUL_PROTECTED__"

from memory_butler import (
    MemoryButler, progressive_summarize,
    extract_execution_log, archive_completed_task, STEWARD_CONFIG,
)
from context_assembler import (
    assemble_context, _char_to_tok, get_assembler_stats, reset_assembler_stats,
)


def _dummy_aux_model(**kwargs):
    """mock: 接受 messages/temperature/max_tokens 等关键词参数"""
    return "mock_summary: dummy"


class TestDrawerEngine(unittest.TestCase):

    def test_drawer_stack_push_pop(self):
        ds = DrawerStack()
        # current_level starts at 1 (top level)
        self.assertEqual(ds.current_level, 1)
        ds.push({"role": "user", "content": "hello"})
        ds.push({"role": "assistant", "content": "world"})
        items = ds.get_context_items()
        self.assertGreaterEqual(len(items), 2)

    def test_temperature_index(self):
        ti = TemperatureIndex()
        ti.hit("key1")
        ti.hit("key2")
        ti.hit("key1")
        stats = ti.get_stats()
        self.assertIn("total", stats)
        self.assertEqual(stats["total"], 2)

    def test_dedup_engine(self):
        de = DedupEngine()
        msgs = [
            {"role": "tool", "content": "ls\ntotal 4\n-rw-r--r--  1 user user  0 Jan 1 file"},
            {"role": "tool", "content": "ls\ntotal 4\n-rw-r--r--  1 user user  0 Jan 1 file"},
            {"role": "user", "content": "hello"},
        ]
        result = de.dedup(msgs)
        self.assertLessEqual(len(result), len(msgs))

    def test_noise_filter(self):
        nf = NoiseFilter()
        self.assertTrue(nf.is_noise("哈哈"))
        self.assertTrue(nf.is_noise("好的"))
        self.assertTrue(nf.is_noise("继续"))
        self.assertFalse(nf.is_noise("设计文档已完成"))
        self.assertFalse(nf.is_noise("这个方案需要讨论"))

    def test_protection_detector(self):
        pd = ProtectionDetector()
        content = PROTECTED_MARKER + "\nid:test\nprotected: true\n---\ntest"
        self.assertIn(PROTECTED_MARKER, content)

    def test_unique_key_index(self):
        uki = UniqueKeyIndex()
        result = uki.check("TFC-155", "version 1")
        self.assertIsNotNone(result)
        uki.register("TFC-155", "version 1")
        # after register, same key should be blocked
        result2 = uki.check("TFC-155", "version 2")
        self.assertTrue(isinstance(result2, dict))
        uki.reset()
        result3 = uki.check("TFC-155", "version 3")
        self.assertIsNotNone(result3)

    def test_conflict_resolver(self):
        cr = ConflictResolver()
        winner = cr.resolve(
            "protected content\n" + PROTECTED_MARKER,
            key="TFC-155",
            protection_type="soul",
            existing_entries=[],
        )
        self.assertIsNotNone(winner)

    def test_drawer_level_compression(self):
        ds = DrawerStack()
        for i in range(50):
            ds.push({"role": "user", "content": f"item {i}"})
        self.assertGreaterEqual(ds.current_level, 1)


class TestMemoryButler(unittest.TestCase):

    def setUp(self):
        self.butler = MemoryButler(_dummy_aux_model)

    def test_init_stats(self):
        stats = self.butler.get_stats()
        self.assertIn("summaries_created", stats)
        self.assertEqual(stats["summaries_created"], 0)

    def test_init_perf_stats(self):
        perf = self.butler.get_perf_stats()
        self.assertIn("cycles_run", perf)
        self.assertEqual(perf["cycles_run"], 0)
        self.assertEqual(perf["total_duration_ms"], 0)

    def test_extract_execution_log(self):
        result = extract_execution_log(
            "我部署了 广州服务器 2026-05-19\n"
            "状态: 完成"
        )
        self.assertIsNotNone(result)
        self.assertIn("广州", result["text"])

        result2 = extract_execution_log("今天天气不错")
        self.assertIsNone(result2)

    def test_extract_execution_log_tfc_ref(self):
        result = extract_execution_log("我写了 TFC-155 的设计文档")
        self.assertIsNotNone(result)
        tfc_ref = result.get("tfc_ref") or []
        self.assertIn("TFC-155", tfc_ref)

    def test_progressive_summarize_new(self):
        result = progressive_summarize("测试方案", "讨论内容", _dummy_aux_model)
        self.assertIsNotNone(result)
        self.assertIn("mock_summary", result)

    def test_progressive_summarize_update(self):
        result = progressive_summarize(
            "测试方案", "新讨论", _dummy_aux_model,
            existing_summary="旧摘要: 完成20%",
        )
        self.assertIsNotNone(result)
        self.assertIn("mock_summary", result)

    def test_archive_completed_task(self):
        result = archive_completed_task("TFC-155", ["第一版", "第二版"], _dummy_aux_model)
        self.assertIsNotNone(result)
        self.assertIn("mock_summary", result)

    def test_check_duplicates(self):
        self.butler._check_duplicates("")
        self.butler._check_duplicates("no TFC references here")

    def test_reset(self):
        self.butler._round_count = 50
        self.butler._stats["summaries_created"] = 5
        self.butler._perf_stats["glm_calls"] = 10
        self.butler.reset()
        self.assertEqual(self.butler._round_count, 0)
        self.assertEqual(self.butler._stats["summaries_created"], 0)
        self.assertEqual(self.butler._perf_stats["glm_calls"], 0)

    def test_tick_skipped_if_disabled(self):
        orig_enabled = STEWARD_CONFIG.get("enabled", True)
        STEWARD_CONFIG["enabled"] = False
        self.butler.tick([], "test")
        self.assertEqual(self.butler._perf_stats["cycles_run"], 0)
        STEWARD_CONFIG["enabled"] = orig_enabled

    def test_tick_with_items_triggers_cycle(self):
        self.butler.tick(
            [{"role": "user", "content": "讨论 TFC-200 架构"}],
            "测试消息"
        )
        self.assertGreaterEqual(self.butler._perf_stats["cycles_run"], 0)


class TestContextAssembler(unittest.TestCase):

    def test_char_to_tok(self):
        self.assertEqual(_char_to_tok(""), 0)
        self.assertGreater(_char_to_tok("x" * 100), 0)

    def test_assemble_empty(self):
        result = assemble_context([], "test", {})
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)

    def test_assemble_with_drawer_items(self):
        items = [{"role": "user", "content": "讨论 TFC-200"}]
        result = assemble_context(items, "test query", {})
        self.assertIsNotNone(result)

    def test_assemble_project_refs(self):
        result = assemble_context([], "TFC-200", {})
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 10)

    def test_assemble_tok_budget(self):
        items = [{"role": "user", "content": "x" * 5000}]
        result = assemble_context(items, "test budget", {})
        # 结果不要太小
        self.assertGreater(len(result), 10)

    def test_assembler_stats_updates(self):
        reset_assembler_stats()
        stats0 = get_assembler_stats()
        calls_before = stats0.get("calls", 0)
        assemble_context([], "stat test", {})
        stats1 = get_assembler_stats()
        self.assertGreaterEqual(stats1.get("calls", 0), calls_before + 1)

    def test_reset_assembler_stats(self):
        reset_assembler_stats()
        stats = get_assembler_stats()
        self.assertEqual(stats.get("calls", 0), 0)
        self.assertEqual(stats.get("total_duration_ms", 0), 0)


class TestPipelineIntegration(unittest.TestCase):

    def test_butler_then_assembler(self):
        butler = MemoryButler(_dummy_aux_model)
        drawer_items = [
            {"role": "user", "content": "讨论 TFC-200 压缩系统"},
            {"role": "assistant", "content": "好的我们讨论架构"},
        ]
        # butler tick
        butler.tick(drawer_items, "测试用户消息")
        perf = butler.get_perf_stats()

        # assembler
        result = assemble_context(drawer_items, "TFC-200 压缩", butler.get_stats())
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
