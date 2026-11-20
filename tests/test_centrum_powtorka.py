from __future__ import annotations

from pathlib import Path

from tests.fixtures.centrum_processes import preparing_centrum, run_to_end


def test_ten_sam_komunikat_do_maksa_przy_ponownym_uruchomieniu_nie_jest_powtorka(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.internal_template_path.unlink()
    first = run_to_end(centrum, dry_run=True)["result"]

    again = run_to_end(centrum, dry_run=True)["result"]

    assert [(result["stop_kind"], result["diagnosis"]) for result in (first, again)] == [("for_maks", "on_request")] * 2
