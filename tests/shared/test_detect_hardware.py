from unittest.mock import patch

from infrastructure.setup.detect_hardware import detect_hardware


def test_detects_spark_profile():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "NVIDIA DGX A100, 81920\n"
        mock_run.return_value.returncode = 0
        profile = detect_hardware()
    assert profile.name == "spark"
    assert profile.max_users == 20


def test_detects_rtx3080_12gb():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "NVIDIA GeForce RTX 3080, 12288\n"
        mock_run.return_value.returncode = 0
        profile = detect_hardware()
    assert profile.name == "rtx3080_12gb"
    assert profile.embedding_dim == 1024


def test_falls_back_to_cpu_when_no_gpu():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        profile = detect_hardware()
    assert profile.name == "cpu"
    assert profile.max_users == 0
