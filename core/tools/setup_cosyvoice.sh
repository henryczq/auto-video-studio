#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COSYVOICE_DIR="${ROOT_DIR}/third_party/CosyVoice"
MODEL_NAME="${COSYVOICE_MODEL_NAME:-Fun-CosyVoice3-0.5B-2512_RL}"
MODEL_SOURCE_NAME="${MODEL_NAME%_RL}"
MODEL_DIR="${COSYVOICE_DIR}/pretrained_models/${MODEL_NAME}"
RL_LLM_URL="${COSYVOICE_RL_LLM_URL:-}"
export MODEL_NAME MODEL_SOURCE_NAME
REQ_FILE="${ROOT_DIR}/.cosyvoice-requirements.rocm.txt"
VENV_DIR="${COSYVOICE_VENV:-${ROOT_DIR}/.venv-cosyvoice-rocm}"

cd "${ROOT_DIR}"

if [[ ! -d "${COSYVOICE_DIR}" ]]; then
  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "${COSYVOICE_DIR}"
else
  git -C "${COSYVOICE_DIR}" submodule update --init --recursive
fi

PYTHON_BIN="${COSYVOICE_PYTHON:-python3}"
if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv --system-site-packages "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"
PYTHON_BIN="python"

"${PYTHON_BIN}" - <<'PY'
import torch
import torchaudio
print(f"using existing torch: {torch.__version__}")
print(f"using existing torchaudio: {torchaudio.__version__}")
print(f"torch cuda available: {torch.cuda.is_available()}")
if "rocm" not in torch.__version__:
    print("warning: torch version string does not include rocm")
PY

cat > "${REQ_FILE}" <<'REQ'
tqdm
HyperPyYAML
modelscope
conformer
diffusers
gdown
grpcio
grpcio-tools
hydra-core
inflect
librosa
lightning
matplotlib
omegaconf
onnx
onnxruntime
protobuf
pyarrow
pydantic
pyworld
rich
soundfile
tensorboard
transformers==4.51.3
x-transformers
wetext
wget
fastapi
uvicorn
REQ

"${PYTHON_BIN}" -m pip install -r "${REQ_FILE}" \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
"${PYTHON_BIN}" -m pip install tiktoken \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
"${PYTHON_BIN}" -m pip install --no-deps openai-whisper \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com

"${PYTHON_BIN}" - <<'PY'
import os
from pathlib import Path
from modelscope import snapshot_download

model_name = os.environ["MODEL_NAME"]
model_source_name = os.environ["MODEL_SOURCE_NAME"]
model_dir = Path("third_party/CosyVoice/pretrained_models") / model_name
model_dir.mkdir(parents=True, exist_ok=True)
snapshot_download(f"FunAudioLLM/{model_source_name}", local_dir=str(model_dir))
print(f"model ready: {model_dir}")
PY

if [[ -n "${RL_LLM_URL}" ]]; then
  curl -L "${RL_LLM_URL}" -o "${MODEL_DIR}/llm.rl.pt"
  echo "rl weights ready: ${MODEL_DIR}/llm.rl.pt"
fi

echo "CosyVoice ready:"
echo "  source ${VENV_DIR}/bin/activate"
echo "  model: ${MODEL_DIR}"
