from __future__ import annotations


def main() -> None:
    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover - depends on local PortAudio install
        print(f"sounddevice import failed: {exc}")
        return

    print(sd.query_devices())


if __name__ == "__main__":
    main()
