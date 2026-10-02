"""GUI/MCP processes must not reuse one another's stale preview or Drive plan."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock
from controls import Controls
from drive_control import PendingChanges, device_revision, mark_device_changed
from test_controls import current, info, IDENTIFIER
from test_drive_control import reading

class SharedStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bandbox-shared-')
        self.path = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def controller(self):
        return Controls(self.path,self.path,asyncio.Lock(),AsyncMock(return_value=current()),lambda:IDENTIFIER)
    async def test_another_controller_invalidates_preview_without_selection_change(self):
        first, second = self.controller(), self.controller()
        first.remember(info()); second.remember(info())
        self.assertTrue(first.preview_valid()); self.assertTrue(second.preview_valid())
        first.mark_mutation()
        self.assertTrue(first.preview_valid()); self.assertFalse(second.preview_valid())
        with self.assertRaises(ValueError):
            await second.snapshot(1, False)
    async def test_invalid_preview_is_not_promoted_by_own_mutation(self):
        first, second = self.controller(), self.controller()
        first.remember(info()); second.mark_mutation(); first.mark_mutation()
        self.assertIsNone(first.preview)
    async def test_prepared_drive_token_is_rejected_after_external_mutation(self):
        plans = PendingChanges(revision=lambda:device_revision(self.path))
        prepared = plans.prepare(reading(),40,41,'American Clean',True)
        mark_device_changed(self.path)
        with self.assertRaisesRegex(ValueError,'Another controller'):
            plans.consume(prepared['change_token'])
    async def test_recent_drive_report_is_rejected_after_external_mutation(self):
        plans = PendingChanges(revision=lambda:device_revision(self.path))
        prepared = plans.prepare(reading(),40,41,'American Clean',True)
        plan,_ = plans.consume(prepared['change_token'])
        plans.record_verified_change(plan)
        mark_device_changed(self.path)
        with self.assertRaises(ValueError):
            plans.prepare(reading(),41,40,'American Clean',True,'recent_verified_change')

if __name__=='__main__': unittest.main()
