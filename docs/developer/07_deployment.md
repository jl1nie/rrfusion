# デプロイとメンテナンス

本章では、RRFusionシステムの構築・運用・監視方法を解説します。

## 1. 環境構築

### システム要件

**ハードウェア:**
- CPU: 4 core以上
- RAM: 8GB以上
- Storage: 100GB以上（特許データベースの規模に依存）

**ソフトウェア:**
- OS: Linux（Ubuntu 20.04+推奨）/ macOS / Windows + WSL2
- Python: 3.10+
- PostgreSQL: 13+ または Elasticsearch: 7.10+

### Python環境

**依存ライブラリ:**
```
# requirements.txt
fastapi>=0.100.0
uvicorn>=0.23.0
mcp>=0.1.0  # Model Context Protocol SDK
psycopg2-binary>=2.9.0  # PostgreSQL
elasticsearch>=8.0.0  # Elasticsearch（オプション）
numpy>=1.24.0
scikit-learn>=1.3.0
pyyaml>=6.0
```

**インストール:**
```bash
# 仮想環境作成
python3 -m venv venv
source venv/bin/activate

# 依存ライブラリインストール
pip install -r requirements.txt
```

### データベースセットアップ

**PostgreSQL:**
```bash
# PostgreSQLインストール
sudo apt install postgresql postgresql-contrib

# データベース作成
sudo -u postgres createdb rrfusion_patents

# スキーマ作成
psql -U postgres -d rrfusion_patents -f schema.sql
```

**schema.sql:**
```sql
CREATE TABLE patents (
  doc_id VARCHAR PRIMARY KEY,
  pub_id VARCHAR UNIQUE,
  app_id VARCHAR,
  title TEXT,
  abst TEXT,
  claim TEXT,
  desc TEXT,
  fi_norm VARCHAR[],
  fi_full VARCHAR[],
  ft VARCHAR[],
  country VARCHAR(2),
  filing_date DATE,
  publication_date DATE,
  applicant TEXT,
  inventor TEXT[]
);

CREATE INDEX idx_pub_id ON patents(pub_id);
CREATE INDEX idx_app_id ON patents(app_id);
CREATE INDEX idx_fi_norm ON patents USING GIN(fi_norm);
CREATE INDEX idx_fi_full ON patents USING GIN(fi_full);
CREATE INDEX idx_ft ON patents USING GIN(ft);
CREATE INDEX idx_publication_date ON patents(publication_date);
```

## 2. 設定ファイル

### config.yaml

```yaml
# RRFusion MCP Server Configuration

server:
  host: "0.0.0.0"
  port: 8000
  debug: true

database:
  type: "postgresql"  # "postgresql" | "elasticsearch"
  host: "localhost"
  port: 5432
  database: "rrfusion_patents"
  user: "postgres"
  password: "your_password"

backend:
  fulltext_endpoint: "http://localhost:9200"  # Elasticsearch
  semantic_endpoint: "http://localhost:8001"  # Semantic search service

fusion:
  default_weights:
    fulltext: 1.0
    semantic: 0.8
    code: 0.3
  default_lane_weights:
    recall: 1.0
    precision: 1.0
    semantic: 0.8
  default_pi_weights:
    code: 0.4
    facet: 0.3
    lane: 0.3
  default_rrf_k: 60
  default_beta_fuse: 1.2

cache:
  enabled: true
  ttl: 3600  # 1 hour
  max_size: 1000

logging:
  level: "INFO"  # DEBUG | INFO | WARNING | ERROR
  file: "logs/rrfusion.log"
```

### SystemPrompt配置

```bash
# SystemPromptファイルの配置
cp SystemPrompt_v1_5.yaml /path/to/rrfusion/config/

# 環境変数で指定
export RRFUSION_SYSTEMPROMPT=/path/to/rrfusion/config/SystemPrompt_v1_5.yaml
```

## 3. サーバ起動

### MCPサーバ起動

```bash
# 開発モード
uvicorn rrfusion.mcp_server:app --reload --host 0.0.0.0 --port 8000

# 本番モード
uvicorn rrfusion.mcp_server:app --host 0.0.0.0 --port 8000 --workers 4
```

### systemdサービス化（本番）

```ini
# /etc/systemd/system/rrfusion-mcp.service
[Unit]
Description=RRFusion MCP Server
After=network.target postgresql.service

[Service]
Type=simple
User=rrfusion
WorkingDirectory=/opt/rrfusion
Environment="PATH=/opt/rrfusion/venv/bin"
ExecStart=/opt/rrfusion/venv/bin/uvicorn rrfusion.mcp_server:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# サービス有効化
sudo systemctl enable rrfusion-mcp
sudo systemctl start rrfusion-mcp
sudo systemctl status rrfusion-mcp
```

## 4. ログとデバッグ

### ログ設定

**logging_config.py:**
```python
import logging
import logging.handlers

def setup_logging(log_file: str, level: str = "INFO"):
    """
    Setup logging configuration
    """
    log_level = getattr(logging, level.upper())

    # Create logger
    logger = logging.getLogger("rrfusion")
    logger.setLevel(log_level)

    # File handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
```

### デバッグモード

**config.yaml:**
```yaml
server:
  debug: true

logging:
  level: "DEBUG"
```

**ログ出力例:**
```
2025-11-30 10:15:23 - rrfusion - INFO - Received rrf_search_fulltext_raw request
2025-11-30 10:15:23 - rrfusion - DEBUG - Query: (顔認証 AND 遮蔽)
2025-11-30 10:15:23 - rrfusion - DEBUG - Filters: [{'lop': 'and', 'field': 'fi', 'op': 'in', 'value': ['G06V10/82']}]
2025-11-30 10:15:24 - rrfusion - INFO - Search completed: 423 hits
```

## 5. パフォーマンス監視

### メトリクス収集

**Prometheus + Grafana（推奨）:**

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Metrics
request_count = Counter('rrfusion_requests_total', 'Total requests', ['tool'])
request_duration = Histogram('rrfusion_request_duration_seconds', 'Request duration', ['tool'])
fusion_score_distribution = Histogram('rrfusion_fusion_scores', 'Fusion score distribution')
active_requests = Gauge('rrfusion_active_requests', 'Active requests')

# Instrument
@request_duration.labels(tool='rrf_search_fulltext_raw').time()
def rrf_search_fulltext_raw(...):
    request_count.labels(tool='rrf_search_fulltext_raw').inc()
    active_requests.inc()
    try:
        # Process
        ...
    finally:
        active_requests.dec()
```

### 監視項目

**システムメトリクス:**
- CPU使用率
- メモリ使用率
- ディスクI/O

**アプリケーションメトリクス:**
- リクエスト数（ツール別）
- レスポンスタイム（ツール別）
- エラー率

**検索メトリクス:**
- 検索実行時間
- ヒット数分布
- 構造メトリクス（Fproxy/LAS/CCW）

### アラート設定

**Prometheus alerting rules:**
```yaml
groups:
  - name: rrfusion_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(rrfusion_errors_total[5m]) > 0.1
        for: 5m
        annotations:
          summary: "High error rate detected"

      - alert: SlowResponse
        expr: histogram_quantile(0.95, rrfusion_request_duration_seconds) > 5
        for: 5m
        annotations:
          summary: "95th percentile response time > 5s"
```

## 6. セキュリティ考慮事項

### 認証・認可

**API Key認証（MVP）:**
```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("RRFUSION_API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key
```

**将来の拡張（OAuth2）:**
```python
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Verify JWT token
    ...
```

### HTTPS

**本番環境では必須:**
```bash
# Let's Encrypt証明書取得
sudo certbot --nginx -d rrfusion.example.com

# Nginx設定
server {
    listen 443 ssl;
    server_name rrfusion.example.com;

    ssl_certificate /etc/letsencrypt/live/rrfusion.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rrfusion.example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### データプライバシー

**検索履歴の保護:**
- ログにクエリを記録する場合、個人情報が含まれないか確認
- ログのアクセス制限
- 定期的なログローテーション・削除

## 7. バックアップとリカバリ

### データベースバックアップ

**PostgreSQL:**
```bash
# 定期バックアップ（cron）
0 2 * * * pg_dump -U postgres rrfusion_patents | gzip > /backup/rrfusion_patents_$(date +\%Y\%m\%d).sql.gz

# リストア
gunzip -c /backup/rrfusion_patents_20251130.sql.gz | psql -U postgres rrfusion_patents
```

**Elasticsearch:**
```bash
# Snapshotリポジトリ設定
curl -X PUT "localhost:9200/_snapshot/backup_repo" -H 'Content-Type: application/json' -d'
{
  "type": "fs",
  "settings": {
    "location": "/backup/elasticsearch"
  }
}'

# Snapshot作成
curl -X PUT "localhost:9200/_snapshot/backup_repo/snapshot_$(date +\%Y\%m\%d)"

# リストア
curl -X POST "localhost:9200/_snapshot/backup_repo/snapshot_20251130/_restore"
```

### 設定ファイルのバージョン管理

```bash
# Gitで管理
cd /opt/rrfusion/config
git init
git add SystemPrompt_v1_5.yaml config.yaml
git commit -m "Initial configuration"
```

## 8. トラブルシューティング

### よくある問題

**問題1: 検索が遅い**

**原因:**
- インデックスが作成されていない
- データベース接続プールが不足

**対処:**
```sql
-- インデックス確認
\di

-- インデックス作成
CREATE INDEX idx_fi_norm ON patents USING GIN(fi_norm);

-- 接続プール設定（config.yaml）
database:
  pool_size: 20
  max_overflow: 10
```

**問題2: メモリ不足**

**原因:**
- 大量の文献を一度に処理

**対処:**
```python
# ページネーション
def get_documents_batch(doc_ids: List[str], batch_size: int = 100):
    for i in range(0, len(doc_ids), batch_size):
        batch = doc_ids[i:i+batch_size]
        yield load_documents(batch)
```

**問題3: Elasticsearch接続エラー**

**原因:**
- Elasticsearchが起動していない
- ネットワーク設定

**対処:**
```bash
# Elasticsearch状態確認
curl -X GET "localhost:9200/_cluster/health"

# 再起動
sudo systemctl restart elasticsearch
```

## まとめ

デプロイとメンテナンスの要点:

**環境構築:**
- Python 3.10+, PostgreSQL/Elasticsearch
- 依存ライブラリインストール

**設定:**
- config.yaml, SystemPrompt_v1_5.yaml
- 環境変数

**起動:**
- 開発モード: uvicorn --reload
- 本番モード: systemdサービス化

**監視:**
- ログ（RotatingFileHandler）
- メトリクス（Prometheus + Grafana）
- アラート

**セキュリティ:**
- API Key認証（MVP）
- HTTPS（本番）
- データプライバシー

**バックアップ:**
- データベース定期バックアップ
- 設定ファイルのGit管理

---

以上で、開発者向けドキュメントは完了です。

次に進むべきこと:
- システムの実装
- テスト・検証
- 本番環境へのデプロイ
- 継続的な改善
