#!/bin/bash
set -e

cd "$(dirname "$0")/.." || exit 1

echo "=========================================="
echo "  Auto Video Studio - Docker 部署"
echo "=========================================="
echo ""

usage() {
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  build       构建 Docker 镜像"
    echo "  start       启动服务"
    echo "  stop        停止服务"
    echo "  restart     重启服务"
    echo "  logs        查看日志"
    echo "  status      查看状态"
    echo "  gpu         启动 GPU 版本"
    echo "  clean       清理镜像和容器"
    echo ""
    exit 1
}

case "${1:-}" in
    build)
        echo "[构建镜像]"
        docker-compose -f docker/docker-compose.yml build
        ;;
    start)
        echo "[启动服务]"
        docker-compose -f docker/docker-compose.yml up -d
        echo ""
        echo "服务已启动: http://localhost:1894"
        ;;
    stop)
        echo "[停止服务]"
        docker-compose -f docker/docker-compose.yml down
        ;;
    restart)
        echo "[重启服务]"
        docker-compose -f docker/docker-compose.yml restart
        ;;
    logs)
        docker-compose -f docker/docker-compose.yml logs -f
        ;;
    status)
        docker-compose -f docker/docker-compose.yml ps
        ;;
    gpu)
        echo "[启动 GPU 版本]"
        docker-compose -f docker/docker-compose.yml --profile gpu up -d auto-video-studio-gpu
        echo ""
        echo "GPU 服务已启动: http://localhost:1894"
        ;;
    clean)
        echo "[清理]"
        docker-compose -f docker/docker-compose.yml down -v --rmi local
        docker system prune -f
        ;;
    *)
        usage
        ;;
esac
