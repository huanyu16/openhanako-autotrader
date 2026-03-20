#!/bin/bash
# ============================================================================
# OpenHanako AutoTrader — 一键安装脚本
# ============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "================================================"
echo "  OpenHanako AutoTrader 安装程序"
echo "  项目目录: $PROJECT_DIR"
echo "================================================"
echo ""

# ---------- 1. 创建目录结构 ----------
echo "[1/5] 创建目录结构..."
mkdir -p "$PROJECT_DIR/shared"
mkdir -p "$PROJECT_DIR/servers"
mkdir -p "$PROJECT_DIR/config"
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/logs"
echo "  ✅ shared/ servers/ config/ data/ logs/"

# ---------- 2. 检查 Python ----------
echo ""
echo "[2/5] 检查 Python 环境..."
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v $cmd &>/dev/null; then
        version=$($cmd --version 2>&1 | grep -oP '\d+\.\d+')
        major=$(echo $version | cut -d. -f1)
        minor=$(echo $version | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON=$cmd
            echo "  ✅ $cmd ($version)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ❌ 未找到 Python 3.10+，请先安装 Python"
    exit 1
fi

# ---------- 3. 安装 Python 依赖 ----------
echo ""
echo "[3/5] 安装 Python 依赖..."
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    $PYTHON -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet --disable-pip-version-check 2>&1 | grep -v "already satisfied" || true
    echo "  ✅ 依赖安装完成"
else
    echo "  ⚠️  requirements.txt 不存在，跳过"
fi

# ---------- 4. 配置环境变量 ----------
echo ""
echo "[4/5] 检查环境变量..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        echo "  ✅ 已从 .env.example 创建 .env"
    else
        touch "$PROJECT_DIR/.env"
        echo "  ✅ 已创建空的 .env"
    fi
    echo "  ⚠️  请编辑 .env 填入你的 Alpaca API Key："
    echo "     nano $PROJECT_DIR/.env"
else
    echo "  ✅ .env 已存在"
fi

# ---------- 5. 生成 MCP 配置 ----------
echo ""
echo "[5/5] 生成 OpenHanako MCP 配置..."
MCP_CONFIG="$PROJECT_DIR/config/openhanako_mcp.json"
if [ ! -f "$MCP_CONFIG" ]; then
    cat > "$MCP_CONFIG" << 'MCPEOF'
{
  "mcpServers": {
    "alpaca-trade": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "<你的API_KEY>",
        "ALPACA_SECRET_KEY": "<你的SECRET_KEY>",
        "ALPACA_PAPER_TRADE": "true"
      }
    },
    "strategy-engine": {
      "command": "python",
      "args": ["servers/strategy_engine.py"],
      "cwd": "<项目路径>/openhanako-auto-trader"
    },
    "risk-guard": {
      "command": "python",
      "args": ["servers/risk_guard.py"],
      "cwd": "<项目路径>/openhanako-auto-trader"
    },
    "auto-scheduler": {
      "command": "python",
      "args": ["servers/auto_scheduler.py"],
      "cwd": "<项目路径>/openhanako-auto-trader"
    }
  }
}
MCPEOF
    echo "  ✅ 已生成 config/openhanako_mcp.json"
    echo "  ⚠️  请将 <项目路径> 替换为实际路径，API Key 替换为你的真实 Key"
else
    echo "  ✅ config/openhanako_mcp.json 已存在"
fi

# ---------- 完成 ----------
echo ""
echo "================================================"
echo "  ✅ 安装完成！"
echo ""
echo "  后续步骤："
echo "  1. 编辑 .env 填入 Alpaca API Key"
echo "  2. 运行 uvx alpaca-mcp-server init 安装官方交易 MCP"
echo "  3. 将 config/openhanako_mcp.json 合并到 OpenHanako MCP 配置"
echo "================================================"
