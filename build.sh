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

# Архив с образом QEMU и скриптами запуска (лежит рядом с build.sh)
QEMU_TARBALL="qemu-motioncore-image-202509.tar.xz"

# Список файлов сертификатов, лежащих рядом с build.sh
CHROME_CERT_FILES=("cert1.pem" "cert2.pem" "cert3.pem")

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
    local apt_pkgs=(
        curl wget git ca-certificates
        qtcreator obs-studio python3-tk
        v4l-utils guvcview
        qemu-system-x86
        libnss3-tools
    )

    for pkg in "${apt_pkgs[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
            missing+=("$pkg")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "Устанавливаю системные пакеты: ${missing[*]}"
        export DEBIAN_FRONTEND=noninteractive
        run_apt update -y
        # Флаг --ignore-missing предотвращает сбой скрипта, если какой-то пакет переименован
        run_apt install -y --ignore-missing "${missing[@]}"
        echo "Системные пакеты проверены/установлены."
    else
        echo "Системные apt-пакеты уже установлены."
    fi

    # Установка VS Code через snap
    if ! command -v code >/dev/null 2>&1; then
        echo "Устанавливаю VS Code..."
        if command -v snap >/dev/null 2>&1; then
            if [[ "${EUID}" -eq 0 ]]; then
                snap install --classic code
            elif command -v sudo >/dev/null 2>&1; then
                sudo snap install --classic code
            else
                echo "Ошибка: нужны права root/sudo для установки snap-пакетов." >&2
            fi
        else
            echo "Ошибка: snap не найден, установите VS Code вручную." >&2
        fi
    else
        echo "VS Code уже установлен."
    fi
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
    source "${HOME}/.bashrc"
    echo "UV установлен: $(uv --version)"
}

ensure_venv() {
    if [[ -d .venv ]]; then
        echo "Python-окружение найдено: ${ROOT}/.venv"
        return
    fi

    echo "Python-окружение не найдено. Создаю .venv с Python 3.10..."
    # uv автоматически скачает переносимый бинарник Python 3.10, если в системе версия выше
    uv venv --python 3.10
    echo "Окружение создано: ${ROOT}/.venv"
}

write_clean_pyproject() {
    cat > pyproject.toml <<'EOF'
[project]
name = "motioncore-cht-template"
version = "0.1.0"
description = "Шаблон репозитория для ЧВТ"
readme = "participant.md"
requires-python = ">=3.10,<3.11"
dependencies = [
    "certifi>=2026.7.22",
    "motorcortex-python==0.25.1",
    "requests",
    "PyQt5==5.15.11",
    "opencv-python",
    "numpy",
    "matplotlib",
    "torch",
    "torchvision",
    "torchaudio",
    "ultralytics",
    "pynng",
    "protobuf",
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
    echo "Источник: git+https://***@${API_GIT_REPO}${API_GIT_REF:+@${API_GIT_REF}}"
    uv pip install "${spec}"
    echo "motion-core-API установлен из git."
}

ensure_pyproject_and_deps() {
    if [[ ! -f pyproject.toml ]]; then
        echo "pyproject.toml не найден. Создаю чистый pyproject.toml..."
        write_clean_pyproject
    else
        if grep -q 'motion-core-api' pyproject.toml || grep -q 'motion-core-API' pyproject.toml; then
            echo "Обнаружены ссылки на motion-core в pyproject.toml. Перезаписываю на чистый..."
            write_clean_pyproject
        fi
        echo "pyproject.toml актуален: ${ROOT}/pyproject.toml"
    fi

    echo "Синхронизирую зависимости проекта через uv sync..."
    uv sync

    if [[ -f "${API_TARBALL}" ]]; then
        echo "Найден локальный архив ${API_TARBALL}. Устанавливаю в окружение..."
        uv pip install "${ROOT}/${API_TARBALL}"
        echo "Библиотека установлена."
    else
        echo "Локальный архив ${API_TARBALL} отсутствует — fallback на git..."
        install_api_from_git
    fi
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
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.venv/
venv/
ENV/
env/

# UV / packaging
.uv/

# Certificates
*.pem

# IDE / OS junk
.idea/
.vscode/
.DS_Store
EOF
}

ensure_gitignore() {
    if [[ -f .gitignore ]]; then
        echo ".gitignore уже есть: ${ROOT}/.gitignore"
        return
    fi

    echo ".gitignore не найден. Создаю..."
    write_default_gitignore
    echo ".gitignore создан."
}

setup_qemu_image() {
    local target_dir="${HOME}/robot_sim"
    local archive_path="${ROOT}/${QEMU_TARBALL}"

    echo "---"
    echo "Настраиваю локальный образ QEMU..."

    if [[ -f "${archive_path}" ]]; then
        echo "Найден архив образа QEMU: ${QEMU_TARBALL}"
        mkdir -p "${target_dir}"
        
        echo "Распаковываю в ${target_dir}..."
        tar -xf "${archive_path}" -C "${target_dir}"
        
        echo "Назначаю права на исполнение всем .sh скриптам..."
        find "${target_dir}" -type f -name "*.sh" -exec chmod +x {} +
        
        echo "Готово. Основной скрипт запуска доступен по пути:"
        find "${target_dir}" -type f -name "start-qemu-motioncore.sh"
    else
        echo "Предупреждение: Архив ${QEMU_TARBALL} не найден рядом со скриптом!" >&2
        echo "Пропускаю установку образа QEMU."
    fi
}

install_chrome() {
    if command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1; then
        echo "Google Chrome уже установлен."
        return
    fi

    echo "---"
    echo "Скачиваю и устанавливаю Google Chrome..."
    local temp_deb="/tmp/google-chrome-stable_current_amd64.deb"
    
    wget -q -O "${temp_deb}" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    
    export DEBIAN_FRONTEND=noninteractive
    run_apt install -y "${temp_deb}"
    
    rm -f "${temp_deb}"
    echo "Google Chrome успешно установлен."
}

install_certs_all() {
    local nssdb_dir="${HOME}/.pki/nssdb"
    local system_ca_dir="/usr/local/share/ca-certificates/motioncore"
    
    echo "---"
    echo "Устанавливаю SSL-сертификаты (в Chrome NSS и системное хранилище ОС)..."
    
    # 1. Подготовка базы NSS для Chrome
    mkdir -p "${nssdb_dir}"
    if [[ ! -f "${nssdb_dir}/cert9.db" ]] && [[ ! -f "${nssdb_dir}/cert8.db" ]]; then
        certutil -N -d "sql:${nssdb_dir}" --empty-password
    fi

    # 2. Подготовка системной папки сертификатов
    if [[ "${EUID}" -eq 0 ]] || command -v sudo >/dev/null 2>&1; then
        run_apt install -y ca-certificates >/dev/null 2>&1 || true
        if [[ "${EUID}" -eq 0 ]]; then
            mkdir -p "${system_ca_dir}"
        else
            sudo mkdir -p "${system_ca_dir}"
        fi
    fi

    for cert_file in "${CHROME_CERT_FILES[@]}"; do
        local cert_path="${ROOT}/${cert_file}"
        local cert_name="MotionCore_${cert_file}"
        
        if [[ ! -f "${cert_path}" ]]; then
            echo "Предупреждение: Сертификат ${cert_file} не найден рядом со скриптом. Пропускаю."
            continue
        fi

        # Добавляем в базу NSS Chrome
        certutil -d "sql:${nssdb_dir}" -A -t "C,," -n "${cert_name}" -i "${cert_path}"

        # Копируем в доверенные сертификаты всей ОС Ubuntu
        local crt_name="${cert_file%.*}.crt"
        if [[ "${EUID}" -eq 0 ]]; then
            cp "${cert_path}" "${system_ca_dir}/${crt_name}"
        elif command -v sudo >/dev/null 2>&1; then
            sudo cp "${cert_path}" "${system_ca_dir}/${crt_name}"
        fi
        
        echo "Сертификат ${cert_file} успешно импортирован."
    done

    # Обновляем сертификаты в ОС
    if [[ "${EUID}" -eq 0 ]]; then
        update-ca-certificates >/dev/null 2>&1 || true
    elif command -v sudo >/dev/null 2>&1; then
        sudo update-ca-certificates >/dev/null 2>&1 || true
    fi
}

cleanup_files() {
    echo "---"
    echo "Очищаю рабочую директорию от временных файлов и инсталляторов..."

    # Удаляем архивы
    rm -f "${ROOT}/${API_TARBALL}"
    rm -f "${ROOT}/${QEMU_TARBALL}"

    # Удаляем сертификаты
    for cert in "${CHROME_CERT_FILES[@]}"; do
        rm -f "${ROOT}/${cert}"
    done

    # Удаляем служебный README (остаётся только participant.md)
    rm -f "${ROOT}/README.md"

    # Удаляем сам build.sh в последний момент
    # rm -f "${BASH_SOURCE[0]}"

    echo "Очистка завершена. Оставлены только файлы участников."
}

# --- ОСНОВНОЙ ПОТОК ВЫПОЛНЕНИЯ ---
ensure_system_deps
ensure_uv
ensure_venv
ensure_pyproject_and_deps
ensure_gitignore
ensure_git
setup_qemu_image
install_chrome
install_certs_all
cleanup_files

cat <<EOF

---
Готово! Установка завершена успешно.
Рабочая директория очищена. Доступны:
- examples/
- participant.md
- pyproject.toml
- uv.lock

Активация окружения:
  source .venv/bin/activate

Запуск скриптов:
  uv run python script.py
  uv run code .
EOF
