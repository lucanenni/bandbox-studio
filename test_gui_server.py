"""HTTP boundary and honest-state tests; never connects to Bluetooth."""
import asyncio
import copy
import unittest

import httpx

from gui_server import create_app


PRESET = {"preset_id": 52, "name": "Albert King Blues", "genre": 0,
          "slots": [{"slot_id": 3, "algorithm_id": 6, "config_id": 0,
                     "bypass_raw": 0, "parameters": [{"parameter_id": 0, "value": 41}]}]}
INVENTORY = [{"preset_id": index, "name": f"Factory {index}", "genre": 0} for index in range(1, 28)] + [
    {"preset_id": 51, "name": "Gilmour Lead", "genre": 0},
    {"preset_id": 52, "name": "Albert King Blues", "genre": 0}]


class FakeController:
    def __init__(self):
        self.preview = None
        self.valid = False
        self.calls = []
        self.result_verified = True
        self.pause = None

    def preview_valid(self):
        return self.valid and self.preview is not None

    async def catalog(self):
        return {"slots": [], "models": []}

    async def list_controls(self):
        return {"readable_controls": {}, "settable_controls": {}}

    async def select_preset(self, preset_id: int):
        self.calls.append(("select_preset", {"preset_id": preset_id}))
        if self.pause:
            await self.pause.wait()
        if self.result_verified:
            self.preview = {"info": copy.deepcopy(PRESET)}
            self.valid = True
        return {"verified": self.result_verified, "preset": copy.deepcopy(PRESET)}

    async def set_effect_parameter(self, expected_preset_id: int, slot_id: int, parameter_id: int,
                                   ui_value: int, confirm_saved_settings: bool = False):
        self.calls.append(("set_effect_parameter", {"ui_value": ui_value}))
        if self.result_verified:
            self.preview["info"]["slots"][0]["parameters"][0]["value"] = ui_value
        return {"verified": self.result_verified, "setting_writes": 1}

    async def save_user_preset(self, expected_preset_id: int):
        self.calls.append(("save_user_preset", {}))
        return {"verified": self.result_verified, "preset": copy.deepcopy(self.preview["info"])}

    async def create_preset(self, source_preset_id: int, name: str, genre: int = 0):
        self.calls.append(("create_preset", {"name": name}))
        created = {"preset_id": 53, "name": name, "genre": genre}
        return {"verified": True, "preset": created, "inventory": INVENTORY + [created],
                "operation": {"new_preset_id": 53}}

    async def read_tool(self, control: str, channel: int | None = None, input_type: str | None = None,
                        page: str | None = None):
        self.calls.append(("read_tool", {"control": control}))
        return {"verified": self.result_verified, "state": {"value": 80}}

    async def set_tool(self, control: str, value: bool | int | float | str):
        self.calls.append(("set_tool", {"control": control, "value": value}))
        return {"verified": self.result_verified, "state": {"value": value}}


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controller = FakeController()
        self.reads = 0
        self.refresh_error = None
        async def refresh():
            self.reads += 1
            if self.refresh_error:
                raise self.refresh_error
            return {"current_preset_read_verified": True, "preset_info": copy.deepcopy(PRESET)}, copy.deepcopy(INVENTORY)
        self.app = create_app(self.controller, refresh_reader=refresh)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1:8765")
        bootstrap = (await self.client.get("/api/bootstrap")).json()
        self.token = bootstrap["token"]

    async def asyncTearDown(self):
        await self.client.aclose()

    async def action(self, action, args=None, **kwargs):
        return await self.client.post("/api/action", json={"action": action, "args": args or {}},
                                      headers={"X-CSRF-Token": self.token, **kwargs.pop("headers", {})}, **kwargs)

    async def load(self):
        await self.action("refresh")
        return await self.action("select_preset", {"preset_id": 52})

    async def test_startup_and_cached_gets_never_access_device(self):
        state = (await self.client.get("/api/state")).json()["state"]
        self.assertFalse(state["connected"])
        self.assertFalse(state["editable"])
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.controller.calls, [])

    async def test_security_headers_and_no_cors(self):
        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertNotIn("access-control-allow-origin", response.headers)

    async def test_unknown_host_and_wrong_port_rejected(self):
        for host in ("evil.test:8765", "127.0.0.1", "localhost:9999", "127.0.0.1:8765.evil.test"):
            response = await self.client.get("/api/bootstrap", headers={"Host": host})
            self.assertEqual(response.status_code, 403, host)

    async def test_localhost_exact_port_is_allowed(self):
        response = await self.client.get("/api/bootstrap", headers={"Host": "localhost:8765"})
        self.assertEqual(response.status_code, 200)

    async def test_cross_origin_bootstrap_and_writes_blocked(self):
        for origin in ("https://evil.test", "null", "http://127.0.0.1:9999"):
            response = await self.client.get("/api/bootstrap", headers={"Origin": origin})
            self.assertEqual(response.status_code, 403)
            response = await self.action("refresh", headers={"Origin": origin})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reads, 0)

    async def test_cross_site_and_same_site_are_rejected(self):
        for site in ("cross-site", "same-site"):
            response = await self.client.get("/api/bootstrap", headers={"Sec-Fetch-Site": site})
            self.assertEqual(response.status_code, 403)

    async def test_same_origin_allowed(self):
        response = await self.action("refresh", headers={"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 200)

    async def test_csrf_required_and_wrong_token_rejected(self):
        response = await self.client.post("/api/action", json={"action": "refresh"})
        self.assertEqual(response.status_code, 403)
        response = await self.action("refresh", headers={"X-CSRF-Token": "incorrect"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reads, 0)

    async def test_only_named_actions_are_available(self):
        for action in ("exchange", "saved_detail", "__class__", "delete_preset", "factory_reset"):
            response = await self.action(action)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.controller.calls, [])

    async def test_json_type_limit_and_duplicate_fields(self):
        for body, content_type, expected in (("action=refresh", "text/plain", 400),
                                              ('{"action":"refresh","action":"set_tool"}', "application/json", 400),
                                              ("x" * (32 * 1024 + 1), "application/json", 413)):
            response = await self.client.post("/api/action", content=body,
                headers={"X-CSRF-Token": self.token, "Content-Type": content_type})
            self.assertEqual(response.status_code, expected)
        self.assertEqual(self.reads, 0)

    async def test_wrong_argument_types_unknown_arguments_and_confirm_flag_rejected(self):
        cases = [("select_preset", {"preset_id": True}), ("select_preset", {"preset_id": "52"}),
                 ("select_preset", {"preset_id": 52, "raw_packet": "FF"}),
                 ("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3, "parameter_id": 0,
                                            "ui_value": 42, "confirm_saved_settings": True})]
        for action, args in cases:
            response = await self.action(action, args)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.controller.calls, [])

    async def test_refresh_is_saved_view_and_numbers_are_inventory_positions(self):
        response = await self.action("refresh")
        state = response.json()["state"]
        self.assertFalse(state["editable"])
        self.assertEqual(state["view_role"], "saved")
        self.assertEqual(state["presets"][-2]["display_number"], 28)
        self.assertEqual(state["presets"][-1]["display_number"], 29)
        self.assertEqual(state["current"]["display_number"], 29)
        self.assertEqual(self.reads, 1)

    async def test_saved_read_cannot_enable_editing(self):
        await self.action("refresh")
        response = await self.action("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3,
                                                               "parameter_id": 0, "ui_value": 42})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.controller.calls, [])

    async def test_select_then_edit_and_save_reflects_verified_preview(self):
        response = await self.load()
        self.assertTrue(response.json()["state"]["editable"])
        response = await self.action("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3,
                                                               "parameter_id": 0, "ui_value": 42})
        state = response.json()["state"]
        self.assertTrue(state["dirty"])
        self.assertEqual(state["current"]["slots"][0]["parameters"][0]["value"], 42)
        response = await self.action("save_user_preset", {"expected_preset_id": 52})
        self.assertFalse(response.json()["state"]["dirty"])

    async def test_expired_or_external_revision_blocks_editing(self):
        await self.load()
        self.controller.valid = False
        response = await self.client.get("/api/state")
        self.assertFalse(response.json()["state"]["editable"])
        response = await self.action("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3,
                                                               "parameter_id": 0, "ui_value": 42})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.controller.calls), 1)

    async def test_refresh_keeps_dirty_edits_instead_of_showing_saved_values(self):
        await self.load()
        await self.action("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3,
                                                   "parameter_id": 0, "ui_value": 42})
        response = await self.action("refresh")
        state = response.json()["state"]
        self.assertTrue(state["dirty"])
        self.assertTrue(state["editable"])
        self.assertEqual(state["current"]["slots"][0]["parameters"][0]["value"], 42)

    async def test_refresh_keeps_but_marks_dirty_preview_when_revision_changed(self):
        await self.load()
        await self.action("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3,
                                                   "parameter_id": 0, "ui_value": 42})
        self.controller.valid = False
        response = await self.action("refresh")
        state = response.json()["state"]
        self.assertTrue(state["dirty"])
        self.assertFalse(state["editable"])
        self.assertEqual(state["view_role"], "stale_preview")
        self.assertIn("unverified", state["message"])
        self.assertEqual(state["current"]["slots"][0]["parameters"][0]["value"], 42)

    async def test_unverified_write_is_error_and_preserves_visible_snapshot(self):
        await self.load()
        self.controller.result_verified = False
        response = await self.action("set_effect_parameter", {"expected_preset_id": 52, "slot_id": 3,
                                                               "parameter_id": 0, "ui_value": 42})
        self.assertEqual(response.status_code, 409)
        result = response.json()
        self.assertFalse(result["ok"])
        self.assertFalse(result["state"]["editable"])
        self.assertEqual(result["state"]["current"]["slots"][0]["parameters"][0]["value"], 41)
        self.assertEqual(len(self.controller.calls), 2)

    async def test_create_does_not_select_new_preset(self):
        await self.load()
        response = await self.action("create_preset", {"source_preset_id": 52, "name": "New Blues"})
        state = response.json()["state"]
        self.assertEqual(state["presets"][-1]["display_number"], 30)
        self.assertEqual(state["current"]["preset_id"], 52)
        self.assertEqual([call[0] for call in self.controller.calls], ["select_preset", "create_preset"])

    async def test_onboard_state_is_returned_without_extra_reads(self):
        response = await self.action("read_tool", {"control": "metronome_bpm"})
        self.assertEqual(response.json()["result"]["state"]["value"], 80)
        self.assertEqual(self.reads, 0)

    async def test_busy_action_is_rejected_without_queue_or_second_write(self):
        self.controller.pause = asyncio.Event()
        first = asyncio.create_task(self.action("select_preset", {"preset_id": 52}))
        for _ in range(100):
            if self.controller.calls:
                break
            await asyncio.sleep(0)
        response = await self.action("select_preset", {"preset_id": 51})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["state"]["busy"])
        self.controller.pause.set()
        response = await first
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["state"]["busy"])
        self.assertEqual(len(self.controller.calls), 1)

    async def test_read_failure_does_not_claim_connection(self):
        self.refresh_error = ValueError("Amp not found")
        response = await self.action("refresh")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["state"]["connected"])
        self.assertFalse(response.json()["ok"])


if __name__ == "__main__":
    unittest.main()
