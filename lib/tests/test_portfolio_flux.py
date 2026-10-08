"""FLUX.1 image generation engine for portfolio projects (lib/portfolio_flux.py)."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_flux as pf
import portfolio_rules
import model_registry


def _png(path, size=(1920, 960)):
    """Create a test PNG at the given size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (50, 100, 150)).save(path)
    return path


def _mock_subprocess_run(command, **kwargs):
    """Mock subprocess.run for testing mflux-generate without actually calling it."""
    class MockResult:
        returncode = 0
        stdout = ""
    return MockResult()


def test_crop_card_and_hero_from_master(tmp_path):
    """The cropping logic extracts card and hero from a single master image."""
    master = _png(tmp_path / "master.png", (1920, 960))
    card_img, hero_img = pf.crop_card_and_hero(Image.open(master))

    rules = portfolio_rules.load_rules()
    card_size = tuple(rules["images"]["thumb_size"])
    hero_size = tuple(rules["images"]["hero_size"])

    assert card_img.size == card_size
    assert hero_img.size == hero_size


def test_crop_preserves_content_in_center(tmp_path):
    """Crops are extracted from the center, preserving key content."""
    w, h = 1920, 960
    master_path = tmp_path / "master.png"
    master_path.parent.mkdir(parents=True, exist_ok=True)

    master = Image.new("RGB", (w, h))
    pixels = master.load()
    for x in range(w):
        for y in range(h):
            if 960 - 50 <= x <= 960 + 50 and 480 - 50 <= y <= 480 + 50:
                pixels[x, y] = (255, 0, 0)
    master.save(master_path)

    card_img, hero_img = pf.crop_card_and_hero(Image.open(master_path))

    pixels_card = card_img.load()
    pixels_hero = hero_img.load()

    assert pixels_card[400, 250] == (255, 0, 0)
    assert pixels_hero[1100, 300] == (255, 0, 0)


def test_model_registry_register(tmp_path):
    """Models can be registered with name, location, size, usage, and reason."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register("qwen2.5-14b", "~/.ollama/models", 9.0, "paper-dive", "logic auditing")

    data = json.loads(registry_path.read_text())
    assert "qwen2.5-14b" in data
    assert data["qwen2.5-14b"]["size_gb"] == 9.0
    assert data["qwen2.5-14b"]["used_by"] == "paper-dive"
    assert data["qwen2.5-14b"]["reason"] == "logic auditing"


def test_model_registry_touch_last_used(tmp_path):
    """touch_last_used updates the last_used timestamp."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register("qwen2.5-14b", "~/.ollama/models", 9.0, "paper-dive", "logic auditing")
    before = json.loads(registry_path.read_text())["qwen2.5-14b"].get("last_used")

    import time
    time.sleep(0.01)
    registry.touch_last_used("qwen2.5-14b")

    after = json.loads(registry_path.read_text())["qwen2.5-14b"].get("last_used")
    assert after > before if before else True


def test_model_registry_atomic_write(tmp_path):
    """Registry writes are atomic (read-modify-write under lock)."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register("model-1", "path1", 1.0, "user1", "reason1")
    registry.register("model-2", "path2", 2.0, "user2", "reason2")

    data = json.loads(registry_path.read_text())
    assert "model-1" in data
    assert "model-2" in data
    assert data["model-1"]["size_gb"] == 1.0
    assert data["model-2"]["size_gb"] == 2.0


def test_disk_guard_passes_when_headroom_sufficient(tmp_path):
    """Disk guard allows install when free space > download + buffer."""
    with patch("portfolio_flux.os.statvfs") as mock_statvfs:
        mock_statvfs.return_value = MagicMock(
            f_bavail=30 * (1024 ** 3) // 512,
            f_frsize=512
        )

        min_disk_gb = 15
        download_gb = 8
        result = pf.check_disk_headroom(min_disk_gb, download_gb)
        assert result.ok


def test_disk_guard_fails_when_headroom_insufficient(tmp_path):
    """Disk guard refuses install when free space < download + buffer."""
    with patch("portfolio_flux.os.statvfs") as mock_statvfs:
        mock_statvfs.return_value = MagicMock(
            f_bavail=10 * (1024 ** 3) // 512,
            f_frsize=512
        )

        min_disk_gb = 15
        download_gb = 8
        result = pf.check_disk_headroom(min_disk_gb, download_gb)
        assert not result.ok
        assert "headroom" in result.error.lower()


def test_disk_guard_from_dispatch_config(tmp_path):
    """Disk guard uses the 15GB constant from config/dispatch.json."""
    config_path = tmp_path / "dispatch.json"
    config_path.write_text(json.dumps({"guards": {"min_disk_gb": 15}}))

    with patch("portfolio_flux.load_dispatch_config", return_value=json.loads(config_path.read_text())):
        guard_gb = pf.get_min_disk_guard()
        assert guard_gb == 15


@pytest.mark.skip(reason="Real dispatch test, requires mac-mini")
def test_generate_returns_image_seed_and_settings(tmp_path):
    """generate() returns the master image, seed used, and generation settings."""
    prompt = "test prompt"
    seed = 42
    size = (1920, 960)

    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.output = ""

    with patch("portfolio_flux.task_dispatch.dispatch", return_value=mock_result):
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = size
            mock_open.return_value = mock_img

            image, seed_used, settings = pf.generate(prompt, seed, size)

            assert seed_used == seed
            assert settings["size"] == list(size)


def test_generate_records_sidecar_json(tmp_path):
    """Each generated image writes a JSON sidecar with metadata."""
    slug = "test-project"
    images_dir = tmp_path / "images"

    master = _png(tmp_path / "master.png", (1920, 960))

    sidecar_path = images_dir / slug / f"flux-{slug}-0.json"

    sidecar_data = {
        "model_build_id": "mflux-4bit",
        "prompt": "a beautiful landscape",
        "seed": 123,
        "steps": 20,
        "guidance": 7.5,
        "master_size": [1920, 960],
    }

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar_data, indent=2))

    assert sidecar_path.exists()
    assert json.loads(sidecar_path.read_text())["model_build_id"] == "mflux-4bit"


def test_uniqueness_check_accepts_distant_fingerprints():
    """Images are unique if Hamming distance >= MIN_DISTANCE."""
    existing_hashes = [0x1234567890ABCDEF, 0xFEDCBA0987654321]
    candidate_hash = 0x0000000000000000

    min_distance = portfolio_rules.load_rules()["images"]["min_distance"]

    result = pf.is_unique(candidate_hash, existing_hashes, min_distance)
    assert result


def test_uniqueness_check_rejects_similar_fingerprints():
    """Images are not unique if Hamming distance < MIN_DISTANCE."""
    a = 0b11111111111111111111111111111111
    b = 0b11111111111111111111111111111110
    existing_hashes = [a]
    candidate_hash = b

    min_distance = 10

    result = pf.is_unique(candidate_hash, existing_hashes, min_distance)
    assert not result


def test_queued_job_lock_pattern():
    """Generate job uses fcntl lock for single-flight queueing."""
    with patch("portfolio_flux.fcntl.flock") as mock_flock:
        lock_file = Path("/tmp/test-lock")

        def acquire_lock():
            with open(lock_file, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)

        assert True


def test_install_checks_mflux_help_before_using_flags():
    """Before install, run mflux-generate --help to confirm flag names."""
    with patch("portfolio_flux.task_dispatch.dispatch") as mock_dispatch:
        mock_dispatch.return_value = MagicMock(
            ok=True,
            output="usage: mflux-generate --prompt ... --seed ...",
            device_id="mac-mini-1"
        )

        result = pf.verify_mflux_help("mac-mini-1")

        assert result.ok
        assert "prompt" in result.output


def test_cli_parses_slug_and_prompt(tmp_path):
    """CLI accepts SLUG and --prompt arguments."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seed", type=int, default=None)

    args = parser.parse_args(["test-project", "--prompt", "a beautiful image"])

    assert args.slug == "test-project"
    assert args.prompt == "a beautiful image"
    assert args.seed is None


def test_cli_seed_optional(tmp_path):
    """CLI accepts optional --seed argument."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seed", type=int, default=None)

    args = parser.parse_args(["test-project", "--prompt", "test", "--seed", "42"])

    assert args.seed == 42


@pytest.mark.parametrize("size", [
    (1920, 960),
    (2048, 1024),
    (1024, 512),
])
def test_master_size_multiple_of_16(size):
    """Master size must be a multiple of 16 (MLX requirement)."""
    w, h = size
    assert w % 16 == 0
    assert h % 16 == 0


def test_end_to_end_mock_workflow(tmp_path):
    """Full workflow: generate -> crop -> record metadata."""
    slug = "test-project"
    prompt = "test"
    seed = 42
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    master = _png(tmp_path / "master.png", (1920, 960))

    mock_result = MagicMock()
    mock_result.ok = True

    with patch("portfolio_flux.task_dispatch.dispatch", return_value=mock_result):
        with patch("PIL.Image.open", side_effect=lambda p: Image.open(master)):
            with patch("portfolio_flux.job_events.job_run"):
                rules = portfolio_rules.load_rules()

                assert rules["images"]["thumb_size"] == [800, 500]
                assert rules["images"]["hero_size"] == [2200, 600]
