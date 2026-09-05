#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skillopt_root="$(cd "$repo_root/.." && pwd)/SkillOpt"
venv_root="$repo_root/.venv"
python_bin="${HANDOVER_PYTHON:-python3.11}"
torch_index_url="${HANDOVER_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
skillopt_commit="db46cd9ae7ce12f1dbd73c945185816aa738751d"

for command in git node npm ffmpeg ffprobe nvidia-smi "$python_bin"; do
    command -v "$command" >/dev/null || {
        echo "Missing required command: $command" >&2
        exit 1
    }
done

node -e '
const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 19)) process.exit(1);
' || {
    echo "Node.js >=22.19 is required" >&2
    exit 1
}

ffmpeg_encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
grep -q 'libx264' <<<"$ffmpeg_encoders" || {
    echo "ffmpeg must include the libx264 encoder" >&2
    exit 1
}

test -d "$skillopt_root/.git" || {
    echo "Clone SkillOpt beside 4D-Agent first: $skillopt_root" >&2
    exit 1
}
test "$(git -C "$skillopt_root" rev-parse HEAD)" = "$skillopt_commit" || {
    echo "SkillOpt must be checked out at $skillopt_commit" >&2
    exit 1
}
test -z "$(git -C "$skillopt_root" status --porcelain --untracked-files=no)" || {
    echo "SkillOpt has tracked changes; use a clean checkout" >&2
    exit 1
}

"$python_bin" -m venv "$venv_root"
"$venv_root/bin/python" -m pip install --upgrade pip setuptools wheel
"$venv_root/bin/python" -m pip install \
    torch==2.10.0 torchvision==0.25.0 --index-url "$torch_index_url"
"$venv_root/bin/python" -m pip install -r "$repo_root/requirements.handover.txt"
"$venv_root/bin/python" -m pip install -e "$skillopt_root"

npm ci --prefix "$repo_root/third_party/pi-runtime"
"$venv_root/bin/python" "$repo_root/scripts/patch_pi_cumulative_args.py"

echo "Environment ready at $venv_root"
echo "Next: copy .env.gpt55.example to .env.gpt55, download data/models, then run preflight."
