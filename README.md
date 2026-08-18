# 拾影成文

把 Bilibili 视频整理成可阅读、可引用、可长期保存的 Markdown 知识库。

粘贴一个普通单 P 视频链接后，拾影成文会优先读取公开视频字幕；没有字幕时自动下载音频并转写，再由大语言模型生成知识稿，最后合并到按主题组织的 Markdown 知识库中。

> 请仅处理你有权访问和保存的内容。本项目不会绕过 DRM、地区限制或访问权限，也不提供扫码登录。

## 主要功能

- Web 页面操作，无需手动执行转写或整理脚本。
- 优先使用公开视频字幕；没有字幕时自动进行语音转写。
- 长音频会根据配置自动分段转写。
- 完整转写会通过单次流式响应生成简洁知识稿，再按主题归档。
- 生成以知识主题命名、正文优先的 Markdown 知识条目。
- 一条视频可按实际内容拆分为多个独立主题更新；每个知识点只进入最匹配的主题，避免跨主题重复。
- 自动把相似知识合并到已有主题，并保留更完整的知识表述。
- 主题归档以知识点归纳总结为主，不保留视频标题或时间戳引用。
- 支持失败阶段重试，刷新页面或重启服务后任务记录仍然保留。
- 可在 Web 中预览和复制知识稿、转写结果与各个主题文档。
- 可按分类浏览、预览和下载知识库中的主题文档。
- 可用 AI 将内容重复或层级混乱的主题整理合并为更清晰的知识结构。
- 可在 Web 中配置不同知识库 Profile，控制希望保留的知识范围。
- API Key 只从服务端环境变量读取，不会返回给浏览器或写入知识文档。

当前仅支持普通单 P 视频。遇到多 P 视频时会明确提示不支持，不会只处理其中一部分。

## 界面使用流程

1. 启动服务并打开 <http://127.0.0.1:5175>。
2. 在主页粘贴 Bilibili 视频链接，点击“解析视频”。
3. 确认标题和封面后，点击“生成知识文档”。
4. 在整理队列中查看解析、素材获取、转写、知识稿生成、知识归档和发布进度。
5. 任务完成后，可以预览知识稿、转写内容，以及本次分别更新的各个主题 Markdown；需要按最新 Profile 重新整理时，可点击“重新归档知识”，不会重复转写或生成正文。

页面右上角的“浏览知识库”用于查看已经归档的主题。选中 Markdown 文档后，可以直接预览、下载；内容逐渐变得重复或零散时，也可以点击“整理合并”，让 AI 在不引入外部知识的前提下把相似内容合并成更完整的讨论并重新组织层级。

“知识库设置”用于管理 Profile，弹窗中同时提供了一份内置中文使用说明。

## 知识库 Profile

Profile 用来告诉系统“希望从视频里保留什么知识”。默认 Profile 是空的开放知识库，不限定领域，也没有预设主题。

三种模式的区别：

- `open`（开放）：保留所有有价值的内容，由系统自由建立主题。
- `guided`（引导）：优先使用设定范围和推荐主题；匹配不上时，仍会为其他有价值的知识自由建立新主题。
- `strict`（严格）：只关注设定范围，而且只能归入推荐主题。

所有模式都会自动精简和合并语义相似的知识。用户不需要设置“是否合并”，也不需要了解 Markdown 文件路径。

### 示例：个人成长与学习

可以在 Web 中新建一个 Profile：

- 名称：个人成长与学习
- 模式：引导
- 关注范围：优先提取学习方法、时间管理、沟通协作和健康习惯中可验证、可执行的知识。
- 推荐主题：
  - 学习方法：阅读、记忆、练习、复盘以及建立长期学习习惯的方法。
  - 时间管理：目标拆解、任务安排、注意力管理和合理休息的方法。
  - 沟通协作：清晰表达、倾听反馈、团队协作和处理分歧的方法。
  - 健康习惯：睡眠、运动、饮食和身心平衡方面的健康实践。

当视频提到“每周复盘时记录有效的学习策略”，系统会优先归入“学习方法”；如果已有相似观点，则合并而不是重复添加。

新增推荐主题时只需填写名称和描述。“AI 辅助归类”会判断是否应该复用已有主题；即使 AI 建议暂时不可用，保存时系统也会自动完成内部归类。

项目还提供可导入参考文件：[profiles/learning.json](profiles/learning.json)。Profile 一旦进入 SQLite，之后以 Web 中保存的内容为准。

## 快速启动

### 公共配置

复制环境变量示例并编辑项目根目录的 `config.env`：

```bash
cp config.example.env config.env
```

语音转写和知识稿模型的主要配置如下：

```env
STT_PROVIDER=dashscope_flash
STT_API_KEY=你的语音转写服务密钥
STT_BASE_URL=你的语音转写服务地址
STT_MODEL=你的语音转写模型名称

LLM_BASE_URL=你的知识稿模型接口地址
LLM_MODEL=你的知识稿模型名称
LLM_API_KEY=你的知识稿模型服务密钥
LLM_ENABLE_THINKING=false
```

语音转写模型和知识稿模型完全分开：前者负责音频转写，后者负责把转写结果整理成知识稿。两者的接口、模型和 API Key 均通过 `config.env` 独立配置，不限定具体厂商或模型系列。即使视频有公开字幕、不需要语音转写，生成知识稿仍需要配置知识稿模型。

知识稿使用完整的转写文本，通过单次流式响应生成。模型输出上限使用 Token 而非字数，默认 10000 Token；提示词会优先去除复述和铺垫，保留影响结论的知识与条件。对于支持 `enable_thinking` 参数的模型，建议设置 `LLM_ENABLE_THINKING=false`，避免推理过程耗尽知识稿输出额度。

请不要把包含真实 API Key 的 `config.env` 提交到公开仓库。

两种运行方式共用这一个 `config.env`：本机运行时由后端直接读取，Docker 运行时由 Compose 注入为容器环境变量。两种方式都会使用项目根目录的 `data/`、`source-output/` 和 `knowledge-base/`。

### 一键启动（推荐）

在项目根目录统一运行：

```bash
./scripts/start.sh
```

脚本会自动选择运行方式：检测到可用 Docker 时使用 Docker Compose；没有安装 Docker 时使用本机 FastAPI + Vite。Docker 容器已经运行时，再次执行脚本只会显示当前地址并退出，不会重复启动第二套服务。

如果系统安装了 Docker 命令但 Docker 服务没有启动，脚本会明确报错，不会自动改成本机运行。需要手动指定时可以使用：

```bash
./scripts/start.sh --docker
./scripts/start.sh --local
```

### Docker 方式（服务器推荐）

只需要安装 Docker 和 Docker Compose，不需要在宿主机安装 Python、Node.js 或 FFmpeg：

```bash
docker compose up -d --build
docker compose ps
```

访问 <http://127.0.0.1:5175>。查看日志和停止服务：

```bash
docker compose logs -f
docker compose down
```

修改 `config.env` 后运行 `docker compose up -d --force-recreate`；更新代码或依赖后运行 `docker compose up -d --build`。镜像只包含服务所需的后端、编译后的前端和运行依赖，不包含 Android 工程或 Codex。

### 本机方式（开发调试）

本机需要：

- Python 3.12 或更高版本；
- Node.js 20 或更高版本；
- FFmpeg（没有公开字幕的视频需要）。

首次使用先安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e './backend[dev]'

cd frontend
npm install
cd ..
```

没有安装 Docker 时直接运行统一入口；如果机器已经安装 Docker，则使用 `--local`：

```bash
./scripts/start.sh
./scripts/start.sh --local
```

脚本会启动 FastAPI 后端和 Vite 开发服务器。访问 <http://127.0.0.1:5175>；在启动终端按 `Ctrl+C` 会同时停止前后端。

## 输出文件在哪里

默认使用两个独立目录：`source-output/` 保存每条视频的转写和知识稿，`knowledge-base/` 只保存持续汇总的主题知识：

```text
source-output/
├── 视频标题-BV号/
│   └── parts/P01-视频标题/
│       ├── document.md          # 干净的知识正文
│       ├── transcript.json      # 标准化转写
│       ├── metadata.json        # 视频与处理信息
│       └── knowledge-update.json

knowledge-base/
└── topics/
    ├── index.json
    └── 分类/主题.md             # 持续合并更新的主题知识
```

视频元数据保存在 `metadata.json`，完整转写保存在 `transcript.json`，不会混入知识正文。来源知识稿不会被知识整理器覆盖。同一条视频包含多个独立知识主题时，系统会分别新建或合并到 `topics/` 下不同的 `.md` 文件，而不是按视频生成单一归档文件。

主题更新时间直接使用文件修改时间。SQLite 只保存主题最后一次更新的来源、动作和时间，不额外生成历史副本；需要版本历史时建议对 `knowledge-base/` 使用 Git。

## 运行日志

任务阶段、模型调用、重试和异常日志会写入 `data/logs/backend.log`，Docker 和本机启动方式使用同一目录。日志文件达到 10 MiB 后自动轮转，最多保留 5 个历史文件。

HTTP 访问日志不写入日志文件；Docker 健康检查产生的 `/api/health` 访问日志也不会输出到控制台。需要实时查看容器日志时运行：

```bash
docker compose logs -f
```

## 数据备份与迁移

迁移包包含历史数据库、`source-output/`、`knowledge-base/` 和 `profiles/`，不包含
`config.env`、Cookie、`data/tmp/` 或构建缓存。先停止服务，再执行：

```bash
./scripts/backup-data.sh
```

默认输出到 `migration-backups/`；也可以指定文件名：

```bash
./scripts/backup-data.sh /安全目录/bili-knowledge-data.tar.zst
```

将代码和迁移包放到新机器，手动放置 `config.env`，在服务停止状态下恢复：

```bash
./scripts/restore-data.sh /安全目录/bili-knowledge-data.tar.zst
```

恢复前的现有数据会移动到 `pre-restore-data/`，数据库中的旧项目绝对路径会自动改为
新项目路径。非交互环境需要在恢复命令末尾添加 `--yes`。

## Android 客户端

仓库中的 `android/` 是“拾影成文”原生 Android 客户端，图标和配色与 Web 保持一致。客户端只提供：

- 提交单 P Bilibili 视频任务；
- 查看任务状态、处理阶段和错误；
- 浏览知识库目录并阅读 Markdown。

客户端不会显示或调用 Profile、删除、重试、重新生成和知识重构等管理能力。首次启动需要填写后端根地址：局域网可填写 `192.168.1.20:8000`，部署后可填写 `https://knowledge.example.com`。地址会保存在应用本地，也可以从右上角连接设置中更换。

实体手机在局域网访问开发机时，在 `config.env` 中启用局域网监听：

```env
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

重启后端后，手机与开发机需处于同一网络，并使用开发机的局域网 IP。不要把无鉴权的后端端口直接暴露到公网；服务器部署时应通过 HTTPS 反向代理和访问控制保护接口。

使用 Android Studio（JDK 17、Android SDK 35）打开 `android/` 即可运行。也可以命令行构建：

```bash
cd android
./gradlew testDebugUnitTest assembleDebug
```

调试 APK 输出到 `android/app/build/outputs/apk/debug/app-debug.apk`，支持 Android 8.0（API 26）及以上系统。当前使用 Android 15（API 35）编译并以 API 35 为目标，调试包同时包含 ARM64、ARMv7、x86 和 x86_64 架构，其原生库支持 Android 15 的 16 KB 内存页对齐。

## 常见问题

### 为什么视频没有进入转写阶段？

如果视频提供公开字幕，系统会直接使用字幕，并把语音转写阶段标记为复用或跳过，这是正常行为。

### 为什么提示仅支持单 P？

当前版本有意不支持多 P 视频，避免只处理部分内容造成误解。可以改用普通单 P 视频测试。

### 为什么没有字幕的视频处理较慢？

系统需要下载音频、使用 FFmpeg 切片，再逐段调用语音识别。视频越长，处理时间和接口费用越高。

### 为什么 AI 辅助归类失败？

先到主页“服务配置”测试知识稿模型。即使辅助建议失败，Profile 仍然可以保存，系统会使用安全的内部归类结果。

### Profile 保存后为什么没有生效？

保存和启用是两个动作。新建 Profile 后，请点击“设为当前使用”。当前启用项会显示绿色状态提示。

### 什么时候需要“整理合并”？

当一个主题经过多次归档后出现内容重复、观点平铺或层级混乱时，可以在“浏览知识库”中选中该主题并进行整理合并。整理合并会把相似内容融合成更完整的讨论并重排层级，直接改写对应 Markdown，建议先用 Git 保存重要版本。归档时系统也会在合并已有主题后自动执行一次同样的整理（可通过 `AUTO_REFACTOR_TOPICS` 关闭）。

### 失败任务产生的临时文件在哪里？

临时音频位于 `data/tmp/{job-id}/`，任务成功后会自动清理。失败任务的临时文件可在后端停止后按对应任务目录手动处理。

### 浏览器里看不到最新界面怎么办？

先按 `Ctrl+Shift+R` 强制刷新。本机开发方式需要重新运行 `./scripts/start.sh --local`；Docker 方式在代码更新后需要运行 `docker compose up -d --build`。

## 部署提醒

- SQLite 数据库、`source-output/` 和 `knowledge-base/` 必须放在持久化磁盘中，否则容器重建后会丢失任务与知识文档。
- 两种启动方式默认都只监听本机地址，适合个人使用。
- Profile 管理接口目前没有登录鉴权。部署到公网前，请通过反向代理、访问控制或后续鉴权功能限制管理入口。
- 请妥善保护 `config.env` 和视频 Cookie 文件。

## 开发与测试

运行全部检查：

```bash
.venv/bin/python -m ruff check backend/app backend/tests
.venv/bin/python -m pytest -q backend/tests

cd frontend
npm test
npm run build
```

后端接口文档：<http://127.0.0.1:8000/docs>

主要接口包括：

- 视频解析与任务：`/api/videos`、`/api/jobs`
- 文档与转写：`/api/documents`、`/api/transcripts`
- 服务配置：`/api/settings`
- Profile 管理：`/api/knowledge/profiles`

自动测试不会调用真实 Bilibili 或 AI 服务，不会消耗模型额度。
