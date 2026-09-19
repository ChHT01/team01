#!/usr/bin/env bash
set -euo pipefail

# Fine-grained HTTPS-токен для временного доступа к приватному репозиторию MotionCore API.
# Нужен только если рядом со скриптом нет motion-core-API-0.1.2.tar.gz.
API_TOKEN="REPLACE_WITH_FINE_GRAINED_TOKEN"

# Репозиторий пакета без схемы (token подставляется в HTTPS-URL).
API_GIT_REPO="github.com/AppliedRobotics/motion_core_api.git"
# Тег/ветка/коммит; пустая строка = ветка по умолчанию.
API_GIT_REF=""

API_TARBALL="motion-core-API-0.1.2.tar.gz"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

run_apt() {
    if [[ "${EUID}" -eq 0 ]]; then
        apt-get "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo apt-get "$@"
    else
        echo "Ошибка: нужны права root или sudo для установки пакетов через apt." >&2
        exit 1
    fi
}

ensure_system_deps() {
    local missing=()

    command -v curl >/dev/null 2>&1 || missing+=(curl)
    command -v git >/dev/null 2>&1 || missing+=(git)
    # ca-certificates нужны curl для HTTPS-установки UV
    if ! dpkg -s ca-certificates >/dev/null 2>&1; then
        missing+=(ca-certificates)
    fi

    if [[ ${#missing[@]} -eq 0 ]]; then
        echo "Системные зависимости уже установлены: curl, git"
        return
    fi

    echo "Устанавливаю системные пакеты: ${missing[*]}"
    export DEBIAN_FRONTEND=noninteractive
    run_apt update -y
    run_apt install -y "${missing[@]}"
    echo "Системные пакеты установлены."
}

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        echo "UV уже установлен: $(command -v uv) ($(uv --version))"
        return
    fi

    echo "UV не найден. Устанавливаю..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    export PATH="${HOME}/.local/bin:${PATH}"
    if ! command -v uv >/dev/null 2>&1; then
        echo "Ошибка: UV установился, но не найден в PATH." >&2
        echo "Добавьте ~/.local/bin в PATH и запустите скрипт снова." >&2
        exit 1
    fi

    echo "UV установлен: $(uv --version)"
}

ensure_venv() {
    if [[ -d .venv ]]; then
        echo "Python-окружение найдено: ${ROOT}/.venv"
        return
    fi

    echo "Python-окружение не найдено. Создаю .venv..."
    uv venv
    echo "Окружение создано: ${ROOT}/.venv"
}

write_default_pyproject() {
    # Базовый pyproject (как в шаблоне). При отсутствии tar.gz ссылка на архив
    # будет убрана перед sync, а пакет поставят из git.
    cat > pyproject.toml <<'EOF'
[project]
name = "motioncore-cht-template"
version = "0.1.0"
description = "Шаблон репозитория для ЧВТ"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "motion-core-API @ ./motion-core-API-0.1.2.tar.gz",
    "motorcortex-python>=0.23.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = false
EOF
}

write_pyproject_without_tarball() {
    cat > pyproject.toml <<'EOF'
[project]
name = "motioncore-cht-template"
version = "0.1.0"
description = "Шаблон репозитория для ЧВТ"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "motorcortex-python>=0.23.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = false
EOF
}

api_git_install_url() {
    local url="git+https://x-access-token:${API_TOKEN}@${API_GIT_REPO}"
    if [[ -n "${API_GIT_REF}" ]]; then
        url="${url}@${API_GIT_REF}"
    fi
    printf '%s' "${url}"
}

install_api_from_git() {
    if [[ -z "${API_TOKEN}" || "${API_TOKEN}" == "REPLACE_WITH_FINE_GRAINED_TOKEN" ]]; then
        echo "Ошибка: нет ${API_TARBALL} и не задан API_TOKEN для установки из git." >&2
        echo "Положите архив рядом со скриптом или укажите fine-grained HTTPS-токен в API_TOKEN." >&2
        exit 1
    fi

    local spec
    spec="$(api_git_install_url)"
    echo "Архив ${API_TARBALL} не найден. Ставлю motion-core-API из git-репозитория..."
    # Спека с токеном не печатаем целиком — только хост/путь.
    echo "Источник: git+https://***@${API_GIT_REPO}${API_GIT_REF:+@${API_GIT_REF}}"
    uv pip install "${spec}"
    echo "motion-core-API установлен из git."
}

ensure_pyproject_and_deps() {
    if [[ ! -f pyproject.toml ]]; then
        echo "pyproject.toml не найден. Создаю..."
        write_default_pyproject
        echo "pyproject.toml создан."
    else
        echo "pyproject.toml уже есть: ${ROOT}/pyproject.toml"
    fi

    if [[ -f "${API_TARBALL}" ]]; then
        echo "Найден локальный архив ${API_TARBALL}. Синхронизирую зависимости..."
        uv sync
        return
    fi

    echo "Локальный архив ${API_TARBALL} отсутствует — fallback на установку API из git."
    # Убираем ссылку на отсутствующий tar.gz, иначе uv sync упадёт.
    if grep -q 'motion-core-API-0.1.2.tar.gz' pyproject.toml; then
        write_pyproject_without_tarball
        echo "pyproject.toml обновлён: зависимость API будет поставлена из git."
    fi

    echo "Синхронизирую остальные зависимости из pyproject.toml..."
    uv sync
    install_api_from_git
}

configure_origin() {
    echo "Введите ссылку на удалённый репозиторий"
    echo "(нажмите Enter, чтобы оставить origin пустым)"
    read -r -p "> " remote_url

    if [[ -z "${remote_url}" ]]; then
        echo "Remote origin не задан (пустой)."
        return
    fi

    if git remote get-url origin >/dev/null 2>&1; then
        git remote set-url origin "${remote_url}"
        echo "Remote origin обновлён: ${remote_url}"
    else
        git remote add origin "${remote_url}"
        echo "Remote origin добавлен: ${remote_url}"
    fi
}

ensure_git() {
    # Проверяем именно локальный .git в каталоге скрипта (не родительский репозиторий).
    if [[ -e .git ]]; then
        echo "Предупреждение: git-репозиторий уже инициализирован в ${ROOT}"
        read -r -p "Переинициализировать репозиторий? [y/N] " answer
        case "${answer}" in
            [yY]|[yY][eE][sS]|[дД]|[дД][аА])
                git init
                echo "Репозиторий переинициализирован."
                ;;
            *)
                echo "Репозиторий оставлен без изменений."
                ;;
        esac
    else
        echo "Git-репозиторий не найден. Инициализирую в ${ROOT}..."
        git init
        echo "Репозиторий создан."
    fi

    configure_origin
}

write_default_gitignore() {
    cat > .gitignore <<'EOF'
# --- Python ---
__pycache__/
*.py[cod]
*$py.class
*.so
*.o
*.a
*.dylib
*.pyd
*.egg
*.egg-info/
.eggs/
dist/
build/
develop-eggs/
downloads/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.manifest
*.spec
pip-log.txt
pip-delete-this-directory.txt
.Python
MANIFEST

# Virtual environments
.venv/
venv/
ENV/
env/
.env/

# UV / packaging
uv.lock
.uv/

# Test / coverage / typecheck caches
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
.coverage.*
htmlcov/
.tox/
.nox/
.cache/
.hypothesis/
nosetests.xml
coverage.xml
*.cover
*.py,cover

# Jupyter
.ipynb_checkpoints/

# IDE / OS junk
.idea/
.vscode/
*.swp
*.swo
*~
.DS_Store
Thumbs.db
desktop.ini

# Logs / local secrets
*.log
.env
.env.*
!.env.example
secrets/
*.pem
*.key

# --- Neural network weights & ML dumps (any depth) ---
*.pt
*.pth
*.pt2
*.ckpt
*.safetensors
*.onnx
*.pb
*.h5
*.hdf5
*.keras
*.tflite
*.pkl
*.pickle
*.joblib
*.npy
*.npz
*.npzz
*.mat
*.engine
*.trt
*.mlmodel
*.params
*.gguf
*.ggml
*.weights
*.torchscript
*.bin

# --- Media: photos / video / audio (any depth) ---
*.jpg
*.jpeg
*.png
*.gif
*.bmp
*.tif
*.tiff
*.webp
*.heic
*.heif
*.ico
*.svg
*.raw
*.cr2
*.nef
*.orf
*.sr2
*.mp4
*.avi
*.mov
*.mkv
*.webm
*.wmv
*.flv
*.m4v
*.mpeg
*.mpg
*.3gp
*.ogv
*.mp3
*.wav
*.flac
*.aac
*.ogg
*.m4a
*.wma

# --- Robotics / CV binary dumps (any depth) ---
*.bag
*.mcap
*.pcd
*.ply
*.stl
*.obj
*.fbx
*.dae
*.blend
*.blend1
*.usd
*.usda
*.usdc
*.abc
*.rosbag
*.ulg
*.csv.gz
*.parquet

# Archives (any depth); keep MotionCore API package in the repo
*.zip
*.rar
*.7z
*.tar
*.tar.gz
*.tgz
*.tar.bz2
*.tbz2
*.tar.xz
*.txz
*.iso
*.dmg
!motion-core-API-*.tar.gz

# Native / school binary junk (any depth)
*.exe
*.dll
*.so.*
*.class
*.jar
*.war
*.apk
*.deb
*.rpm
*.msi
*.out
*.lib
*.wasm
*.pyc
*.pyo
core
core.*
*.core
*.su
*.idb
*.pdb
*.ilk
*.exp
*.map
*.elf
*.hex
*.img
*.qcow2
*.vdi
*.vmdk

# Large local data dumps (common folder names, any depth)
**/data/
**/datasets/
**/dataset/
**/weights/
**/checkpoints/
**/runs/
**/outputs/
**/output/
**/results/
**/logs/
**/tmp/
**/temp/
**/cache/
**/.cache/
**/media/
**/videos/
**/images/
**/photos/
**/recordings/
**/captures/
**/dumps/
**/models/
**/pretrained/
**/snapshots/
**/artifacts/
**/wandb/
**/mlruns/
**/lightning_logs/
**/tensorboard/
**/tb_logs/
EOF
}

ensure_gitignore() {
    if [[ -f .gitignore ]]; then
        echo ".gitignore уже есть: ${ROOT}/.gitignore"
        return
    fi

    echo ".gitignore не найден. Создаю с исключениями для Python / CV / робототехники..."
    write_default_gitignore
    echo ".gitignore создан."
}

ensure_system_deps
ensure_uv
ensure_venv
ensure_pyproject_and_deps
ensure_gitignore
ensure_git

cat <<EOF

Готово.

Активация окружения:
  source ${ROOT}/.venv/bin/activate

Запуск Python-скриптов через UV (активация не обязательна):
  uv run python your_script.py
  uv run your_script.py

Примеры:
  uv run python main.py
  uv run python scripts/demo.py
EOF
