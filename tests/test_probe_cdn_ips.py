from __future__ import annotations

import tempfile
import unittest
import ipaddress
from pathlib import Path
from unittest.mock import patch

from probe_cdn_ips import (
    ProbeResult,
    load_candidates,
    parse_statuses,
    sample_spread,
    write_outputs,
)


class ProbeHelpersTest(unittest.TestCase):
    def test_parse_statuses_accepts_values_and_ranges(self) -> None:
        self.assertEqual(parse_statuses("200,204,301-303"), {200, 204, 301, 302, 303})

    def test_sample_spread_skips_ipv4_network_and_broadcast(self) -> None:
        ips = sample_spread(ipaddress.ip_network("192.0.2.0/30"), 4)
        self.assertEqual(ips, ["192.0.2.1", "192.0.2.2"])

    def test_load_candidates_deduplicates_expanded_ips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.txt"
            path.write_text("192.0.2.1\n192.0.2.0/30\n", encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "candidates": path,
                    "limit": None,
                    "sample_strategy": "spread",
                    "sample_per_cidr": 2,
                    "per_prefix_len": 24,
                    "sample_per_prefix": 1,
                },
            )()

            candidates = load_candidates(args)

        self.assertEqual([item.ip for item in candidates], ["192.0.2.1", "192.0.2.2"])

    def test_write_outputs_keeps_same_second_runs_separate(self) -> None:
        rows = [
            {
                "ip": "192.0.2.1",
                "source": "manual",
                "attempts": 1,
                "success": 1,
                "success_rate": 1.0,
                "http_codes": "200",
                "http_versions": "2",
                "connect_ms_p50": 10.0,
                "tls_ms_p50": 20.0,
                "ttfb_ms_p50": 30.0,
                "total_ms_p50": 40.0,
                "speed_bps_avg": 1024.0,
                "last_error": "",
            }
        ]
        results = [
            ProbeResult(
                ip="192.0.2.1",
                attempt=1,
                ok=True,
                code=200,
                http_version="2",
                connect_ms=10.0,
                tls_ms=20.0,
                ttfb_ms=30.0,
                total_ms=40.0,
                speed_bps=1024.0,
                size_bytes=128.0,
                err="",
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("probe_cdn_ips.time.strftime", return_value="20260615-101010"):
                first = write_outputs(out_dir, "cdn.example.com", 443, rows, results)
                second = write_outputs(out_dir, "cdn.example.com", 443, rows, results)

            self.assertNotEqual(first, second)
            self.assertEqual(first.name, "20260615-101010")
            self.assertEqual(second.name, "20260615-101010-02")
            self.assertTrue((first / "summary.tsv").is_file())
            self.assertTrue((second / "summary.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
