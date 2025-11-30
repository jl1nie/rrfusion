#!/usr/bin/env python3
"""Debug script to check fusion metrics calculation.

Usage:
    python scripts/debug_metrics.py <fusion_run_id>

This script connects to Redis and examines the stored metadata for a fusion run
to verify that metrics are being calculated correctly.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rrfusion.storage import RedisStorage


async def debug_metrics(run_id: str):
    """Examine metrics stored for a fusion run."""
    storage = RedisStorage()

    print(f"Fetching metadata for run: {run_id}")
    meta = await storage.get_run_meta(run_id)

    if not meta:
        print(f"❌ Run not found: {run_id}")
        return

    run_type = meta.get("run_type")
    print(f"✅ Run type: {run_type}")

    if run_type != "fusion":
        print(f"⚠️  This is not a fusion run (type={run_type})")
        return

    # Check metrics
    metrics = meta.get("metrics")
    if not metrics:
        print("❌ No metrics found in metadata")
        return

    print("\n📊 Stored Metrics:")
    print(json.dumps(metrics, indent=2))

    # Analyze edge cases
    las = metrics.get("LAS", 0.0)
    ccw = metrics.get("CCW", 0.0)
    s_shape = metrics.get("S_shape", 0.0)
    f_struct = metrics.get("F_struct", 0.0)
    fproxy = metrics.get("Fproxy", 0.0)
    beta_struct = metrics.get("beta_struct", 1.0)

    print("\n🔍 Analysis:")

    # Check LAS
    if las == 0.0:
        print("⚠️  LAS = 0.0 - Possible causes:")
        print("   - Only 1 lane was used")
        print("   - No overlap between lanes")
        source_runs = meta.get("source_runs", [])
        print(f"   - Actual lanes used: {len(source_runs)}")
        for run in source_runs:
            print(f"     * {run.get('lane')} (weight={run.get('weight')})")

    # Check CCW
    if ccw == 0.0:
        print("⚠️  CCW = 0.0 - Possible causes:")
        print("   - No FI codes found in top documents")
        print("   - Documents missing fi_norm metadata")
    elif ccw == 1.0:
        print("⚠️  CCW = 1.0 - All documents have identical FI code")

    # Check F_struct calculation
    beta_sq = beta_struct * beta_struct
    denom = beta_sq * las + ccw
    expected_f_struct = 0.0
    if denom > 0:
        expected_f_struct = (1 + beta_sq) * las * ccw / denom

    print(f"\n📐 F_struct calculation:")
    print(f"   β² = {beta_sq}")
    print(f"   denominator = β² × LAS + CCW = {beta_sq} × {las} + {ccw} = {denom}")
    if denom <= 0:
        print(f"   ⚠️  denominator <= 0, so F_struct = 0.0")
    else:
        print(f"   F_struct = (1 + β²) × LAS × CCW / denom")
        print(f"            = {1 + beta_sq} × {las} × {ccw} / {denom}")
        print(f"            = {expected_f_struct}")

    if abs(f_struct - expected_f_struct) > 0.0001:
        print(f"   ❌ MISMATCH! Stored={f_struct}, Expected={expected_f_struct}")
    else:
        print(f"   ✅ Calculation matches: {f_struct}")

    # Check Fproxy
    lambda_shape = 0.3  # DEFAULT_LAMBDA_SHAPE
    expected_fproxy = f_struct * max(1.0 - lambda_shape * s_shape, 0.0)
    print(f"\n📐 Fproxy calculation:")
    print(f"   λ = {lambda_shape}")
    print(f"   Fproxy = F_struct × max(1.0 - λ × S_shape, 0.0)")
    print(f"          = {f_struct} × max(1.0 - {lambda_shape} × {s_shape}, 0.0)")
    print(f"          = {expected_fproxy}")

    if abs(fproxy - expected_fproxy) > 0.0001:
        print(f"   ❌ MISMATCH! Stored={fproxy}, Expected={expected_fproxy}")
    else:
        print(f"   ✅ Calculation matches: {fproxy}")

    # Check recipe
    recipe = meta.get("recipe", {})
    target_profile = recipe.get("target_profile")
    if target_profile:
        fi_codes = target_profile.get("fi", {})
        ft_codes = target_profile.get("ft", {})
        print(f"\n🎯 Target Profile:")
        print(f"   FI codes: {len(fi_codes)} ({list(fi_codes.keys())[:5]}...)")
        print(f"   FT codes: {len(ft_codes)} ({list(ft_codes.keys())[:5]}...)")

    await storage.close()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_metrics.py <fusion_run_id>")
        print("\nExample:")
        print("  python scripts/debug_metrics.py fusion-abc123def4")
        sys.exit(1)

    run_id = sys.argv[1]
    await debug_metrics(run_id)


if __name__ == "__main__":
    asyncio.run(main())
