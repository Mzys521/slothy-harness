![Slothy 思洛 Logo](logos/word_logo_chinese_withe.png)

# Slothy / 思洛

![Version](https://img.shields.io/badge/version-0.1.0-60DD06)
![License](https://img.shields.io/badge/license-MIT-95611F)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)

**当前版本：0.1.0** · [更新日志](CHANGELOG.md)

Slothy 是一个基于 Python 的智能体 Harness 项目，目标是为桌面应用提供可控的模型调用、工具执行和运行状态管理。仓库同时包含 Vue 前端工作区。

## 当前进度

0.1.0 已包含可运行的 Python 智能体循环：模型提出工具调用，运行器将调用交给抽象执行器，执行结果再返回模型。Core 提供运行状态、取消、截止时间、工具定义与注册契约；Infrastructure 提供 MiMo 模型适配器和计算工具实现。计算工具包括加、减、乘、除和幂运算，均使用 `float` 参数。

Vue 前端工作区可单独开发；桌面宿主、前端桥接层和产品界面仍在后续开发范围内。

## 架构

依赖方向为 `Vue → Presentation → Application → Core`。Infrastructure 实现 Core 定义的接口，Core 保持纯 Python，不依赖具体模型 SDK、桌面框架或操作系统实现。详见 [架构说明](docs/architecture.md)和[开发指南](docs/Slothy-Development-Guide.md)。

| 目录 | 职责 |
| --- | --- |
| `src/slothy/core/runtime/` | `AgentRunner`、`RunnerResult`、Run/Step 状态及取消和截止时间 |
| `src/slothy/core/model/` | 模型提供方接口及模型响应类型 |
| `src/slothy/core/tools/` | 工具定义、注册表、上下文、结果和抽象执行器 |
| `src/slothy/core/agent/` | 预留智能体相关抽象；当前执行循环由 runtime 管理 |
| `src/slothy/infrastructure/app_tools/` | 计算工具定义及具体执行器 |
| `src/slothy/infrastructure/llm/` | 具体模型提供方适配器 |
| `src/slothy/main.py` | 计算工具智能体的命令行示例入口 |
| `frontend/` | Vue 3、TypeScript、Vite 和 Tailwind CSS 工作区 |
| `tests/` | 单元测试与集成测试 |
| `docs/` | 架构、开发约束和设计决策 |

## 本地运行

需要 Python 3.11+。在 PowerShell 中安装 Python 项目：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

使用真实 MiMo 服务运行示例前，在本地 `.env` 中配置 `MIMO_API_KEY`、`MIMO_BASE_URL` 和 `MIMO_MODEL`，然后执行：

```powershell
.\.venv\Scripts\python.exe -m slothy.main
```

示例入口会提交一条固定的计算问题；实际请求会调用配置的模型服务。`.env` 是本地配置，请勿提交密钥。更多环境说明见[开发文档](docs/development.md)。

前端工作区可独立启动；需要与已安装 Vite 版本兼容的 Node.js 和 npm：

```powershell
cd frontend
npm install
npm run dev
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_*.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_*.py -v
```

## 文档与许可

工具定义和注册方式见[工具注册文档](docs/tool-registration.md)，版本变更见[更新日志](CHANGELOG.md)。项目采用 [MIT 许可证](LICENSE)。
