#!/usr/bin/env python3
"""
SystemPrompt.yaml と SystemPrompt.ja.yaml の構造同期を検証するスクリプト

Usage:
    python scripts/validate_systemprompt_sync.py

目的:
    - 英語版と日本語版のYAML構造が一致していることを確認
    - トップレベルキーの一致
    - 重要なセクション（pipeline, lanes, query_construction_policy）の構造一致
    - 差分があれば警告を出力

Exit codes:
    0: 検証成功（構造一致）
    1: 検証失敗（構造不一致）
    2: YAMLパースエラー
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml


def load_yaml(file_path: Path) -> Dict[str, Any]:
    """YAMLファイルを読み込む"""
    try:
        with open(file_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ YAML parse error in {file_path}: {e}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}", file=sys.stderr)
        sys.exit(2)


def get_keys_recursive(data: Any, prefix: str = "") -> Set[str]:
    """
    ネストされた辞書のキーパスを再帰的に取得

    例: {'a': {'b': {'c': 1}}} → {'a', 'a.b', 'a.b.c'}
    """
    keys = set()

    if isinstance(data, dict):
        for key, value in data.items():
            current_path = f"{prefix}.{key}" if prefix else key
            keys.add(current_path)
            keys.update(get_keys_recursive(value, current_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            current_path = f"{prefix}[{idx}]"
            keys.update(get_keys_recursive(item, current_path))

    return keys


def compare_top_level_keys(en: Dict[str, Any], ja: Dict[str, Any]) -> bool:
    """トップレベルキーの一致を確認"""
    en_keys = set(en.keys())
    ja_keys = set(ja.keys())

    # 日本語版特有の説明キーを除外（"説明", "目的" などは許容）
    # 英語版にあって日本語版にないキーをチェック
    missing_in_ja = en_keys - ja_keys
    extra_in_ja = ja_keys - en_keys

    # 日本語版で許容される追加キー（説明用）
    allowed_extra_keys = {
        "説明", "目的", "定義", "使用場面", "使用方針",
        "重要な注意", "注意事項", "良い例", "悪い例",
        "例", "実行内容", "出力", "出力情報", "健全性基準",
        "調整可能パラメータ", "注意", "禁止事項", "出力例",
        "出力内容", "出力レベル", "ペルソナ", "activate条件",
        "入力言語の自動検出", "モード別出力ポリシー",
        "構文", "用語の役割", "分類体系", "フェーズ別ルール",
        "HyDE必須条件", "HyDE生成原則", "HyDE例",
        "A要素_コア技術要素", "B要素_制約条件", "C要素_用途シーン",
        "FI_サブグループ", "FI_分冊識別記号", "FT_Fターム", "CPC_IPC",
        "Phase1_代表公報探索の原則", "Phase2_バッチ検索の原則",
        "recall_lane", "precision_lane", "semantic_lane",
        "target_profile例", "抽出語彙例", "融合パラメータ例",
        "クエリスタイル", "FI使用", "field_boosts", "コード使用",
        "feature_scope", "semantic_style", "使用フェーズ",
        "重要なパラメータ", "パラメータ", "用途", "id_type対応",
        "デフォルト文字数", "変更履歴", "LLMエージェントへの指示",
    }

    # 許容される追加キーを除外
    extra_in_ja_filtered = {k for k in extra_in_ja if k not in allowed_extra_keys}

    success = True

    if missing_in_ja:
        print(f"❌ 日本語版に不足しているトップレベルキー: {sorted(missing_in_ja)}")
        success = False

    if extra_in_ja_filtered:
        print(f"⚠️  日本語版にある予期しない追加キー: {sorted(extra_in_ja_filtered)}")
        # 警告のみ、失敗とはしない

    if success and not missing_in_ja:
        print(f"✓ トップレベルキー一致 ({len(en_keys)} keys)")

    return success


def compare_section_structure(
    en_section: Any,
    ja_section: Any,
    section_name: str,
    depth: int = 0,
    max_depth: int = 3,
) -> bool:
    """
    特定セクションの構造を比較（深さ制限付き）

    Args:
        en_section: 英語版のセクション
        ja_section: 日本語版のセクション
        section_name: セクション名（エラー表示用）
        depth: 現在の深さ
        max_depth: 最大比較深さ（深すぎる比較は避ける）
    """
    if depth > max_depth:
        return True

    if type(en_section) != type(ja_section):
        print(f"❌ {section_name}: 型不一致 (EN: {type(en_section).__name__}, JA: {type(ja_section).__name__})")
        return False

    if isinstance(en_section, dict):
        en_keys = set(en_section.keys())
        ja_keys = set(ja_section.keys())

        # 日本語版の説明キーを除外
        allowed_ja_keys = {
            "説明", "目的", "定義", "使用場面", "使用方針",
            "重要な注意", "注意事項", "良い例", "悪い例",
            "例", "実行内容", "出力", "出力情報", "健全性基準",
            "調整可能パラメータ", "注意", "禁止事項", "出力例",
            "出力内容", "出力レベル", "ペルソナ", "activate条件",
            "入力言語の自動検出", "モード別出力ポリシー",
            "構文", "用語の役割", "分類体系", "フェーズ別ルール",
            "HyDE必須条件", "HyDE生成原則", "HyDE例",
            "A要素_コア技術要素", "B要素_制約条件", "C要素_用途シーン",
            "FI_サブグループ", "FI_分冊識別記号", "FT_Fターム", "CPC_IPC",
            "Phase1_代表公報探索の原則", "Phase2_バッチ検索の原則",
            "recall_lane", "precision_lane", "semantic_lane",
            "target_profile例", "抽出語彙例", "融合パラメータ例",
            "クエリスタイル", "FI使用", "field_boosts", "コード使用",
            "feature_scope", "semantic_style", "使用フェーズ",
            "重要なパラメータ", "パラメータ", "用途", "id_type対応",
            "デフォルト文字数", "変更履歴", "LLMエージェントへの指示",
        }

        ja_keys_filtered = {k for k in ja_keys if k not in allowed_ja_keys}

        missing_in_ja = en_keys - ja_keys_filtered

        if missing_in_ja:
            print(f"❌ {section_name}: 日本語版に不足しているキー: {sorted(missing_in_ja)}")
            return False

        # 共通キーについて再帰的に比較
        common_keys = en_keys & ja_keys_filtered
        success = True
        for key in common_keys:
            if not compare_section_structure(
                en_section[key],
                ja_section[key],
                f"{section_name}.{key}",
                depth + 1,
                max_depth,
            ):
                success = False

        return success

    elif isinstance(en_section, list):
        # リストは長さのみチェック（要素の順序は問わない）
        if len(en_section) != len(ja_section):
            print(f"⚠️  {section_name}: リスト長が異なる (EN: {len(en_section)}, JA: {len(ja_section)})")
            # 警告のみ、失敗とはしない
        return True

    else:
        # プリミティブ型（str, int, bool等）は比較しない（値は異なってOK）
        return True


def main():
    """メイン関数"""
    repo_root = Path(__file__).parent.parent
    en_path = repo_root / "src" / "rrfusion" / "SystemPrompt.yaml"
    ja_path = repo_root / "src" / "rrfusion" / "SystemPrompt.ja.yaml"

    print("=" * 60)
    print("SystemPrompt 英語版・日本語版 構造同期検証")
    print("=" * 60)
    print()

    # YAMLファイル読み込み
    print(f"📖 英語版読み込み: {en_path}")
    en_data = load_yaml(en_path)

    print(f"📖 日本語版読み込み: {ja_path}")
    ja_data = load_yaml(ja_path)
    print()

    # 検証実行
    success = True

    # 1. トップレベルキーの一致
    print("🔍 [1/4] トップレベルキーの一致を確認...")
    if not compare_top_level_keys(en_data, ja_data):
        success = False
    print()

    # 2. pipeline セクション
    print("🔍 [2/4] pipeline セクションの構造を確認...")
    if "pipeline" in en_data and "pipeline" in ja_data:
        if not compare_section_structure(en_data["pipeline"], ja_data["pipeline"], "pipeline"):
            success = False
        else:
            print(f"✓ pipeline セクション構造一致")
    print()

    # 3. lanes セクション
    print("🔍 [3/4] lanes セクションの構造を確認...")
    if "lanes" in en_data and "lanes" in ja_data:
        if not compare_section_structure(en_data["lanes"], ja_data["lanes"], "lanes"):
            success = False
        else:
            print(f"✓ lanes セクション構造一致")
    print()

    # 4. query_construction_policy セクション
    print("🔍 [4/4] query_construction_policy セクションの構造を確認...")
    if "query_construction_policy" in en_data and "query_construction_policy" in ja_data:
        if not compare_section_structure(
            en_data["query_construction_policy"],
            ja_data["query_construction_policy"],
            "query_construction_policy",
        ):
            success = False
        else:
            print(f"✓ query_construction_policy セクション構造一致")
    print()

    # 結果サマリー
    print("=" * 60)
    if success:
        print("✅ 検証成功: 英語版と日本語版の構造が一致しています")
        print("=" * 60)
        sys.exit(0)
    else:
        print("❌ 検証失敗: 構造に不一致があります")
        print("=" * 60)
        print()
        print("修正方法:")
        print("  1. SystemPrompt.ja.yaml の不足キーを追加")
        print("  2. 構造を SystemPrompt.yaml に合わせる")
        print("  3. このスクリプトを再実行")
        sys.exit(1)


if __name__ == "__main__":
    main()
