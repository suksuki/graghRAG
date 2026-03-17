# 首字 / LLM 延迟优化指南

当界面显示「首字 70s+、LLM 72s+」而 **Prompt 只有几百字符、模型已是 9B 仍很慢** 时，常见根因是 **LlamaIndex 的 Ollama 客户端在未显式设置 `context_window` 时，会在首次（或每次）请求前调用 `client.show(model)` 向 Ollama 拉取模型信息**。该调用会阻塞，且可能触发 Ollama **冷加载模型**（几十秒），所以首字延迟与 prefill 本身关系不大。

**本仓库已做修复**：创建 Ollama 客户端时显式传入 `context_window`（及 `num_ctx`、`keep_alive="30m"`），避免触发 `show(model)`，并减少模型被卸载后的冷启动。若仍慢，可按下面顺序排查。

## 1. 换小模型（最有效）

若当前主模型较大（如 35B、9B 等），在 CPU 或显存不足导致部分 CPU 推理时，prefill 会极慢。

**建议：**

- 在「设置」里把 **LLM 模型** 改为：
  - **qwen2.5:7b**：质量与速度折中，首字通常可降到数秒级；
  - **qwen2.5:3b**：更快，适合对延迟敏感、对答案长度要求不高的场景。
- 或直接在 `.env` 中设置：
  ```bash
  LLM_MODEL=qwen2.5:7b
  ```
  保存后重启 API 服务。

图抽取仍使用 `EXTRACTION_MODEL`（默认 qwen2.5:7b），无需改。

## 2. 限制 Ollama 上下文（num_ctx / context_window）

本仓库在创建 Ollama 客户端时已显式设置 `context_window` 与 `num_ctx`（默认 2048，可由 `LLM_NUM_CTX` 覆盖），从而**避免 LlamaIndex 调用 `client.show(model)` 导致的阻塞与冷启动**。若需更小上下文以进一步加速 prefill，可在 `.env` 中设置 `LLM_NUM_CTX=1024` 后重启 API。

## 3. 确保 Ollama 用 GPU

- **Linux**：安装 GPU 驱动与 CUDA，Ollama 会自动用 GPU。
- **Docker**：需把 GPU 映射进容器（`nvidia-docker` 或 `--gpus all`），并保证容器内能看到 GPU。
- 在 Ollama 所在机器上可运行：
  ```bash
  ollama run qwen2.5:7b "你好"
  ```
  观察首字是否在几秒内出现；若仍要几十秒，多半是 CPU 或显存不足导致部分/全部 CPU 推理。

## 4. 已做的应用层优化（无需再改）

- **Context**：`context_builder` 已限制 `MAX_CONTEXT_CHUNKS=3`、`MAX_CHARS_PER_CHUNK=150`、`MAX_TOTAL_CHARS=800`，单句截断，控制 prompt 体积。
- **Prompt**：`prompt_builder` 使用极简 system（「Answer directly. No reasoning. Max 2 sentences.」）与结尾「Answer:」，减少模型内部 planning。
- **Ollama 主模型**：初始化时传入 `thinking=False`（关闭思考输出）、`num_predict`（如 64）、`temperature=0`，限制生成长度与首字干扰。
- **流式**：查询走 `POST /query/stream`，首字到达即开始展示；后端过滤 thinking，仅推送最终正文。

若仍慢，优先检查：**设置/ .env 中的 `LLM_MODEL` 是否为更小模型（如 7b/3b）**、**Ollama 是否在用 GPU**、**是否设置了 LLM_NUM_CTX**。
