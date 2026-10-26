"""테스트용 임시 폴더 위치. 저장소 루트의 .superpowers(무시 파일)를 만들어 쓴다(D-001)."""
from pathlib import Path


def superpowers_dir() -> str:
    path = Path(__file__).resolve().parents[3] / ".superpowers"
    path.mkdir(exist_ok=True)
    return str(path)
