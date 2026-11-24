def acoustic_command(args):
    import json
    from . import acoustic_profiles as profiles
    from .config import edit_config, init_config, load_config
    from .lock import PIDLock

    path = init_config(args.config)
    lock = PIDLock()
    if not lock.acquire():
        raise ValueError("Stop the TableTap listener before changing acoustic profiles")
    try:
        cfg = load_config(path)
        if args.operation == "list":
            cal = cfg.get("calibration", {})
            return {"message": "Desk profiles: " + ", ".join(sorted(cal.get("profiles", {}))),
                    "active":cal.get("active_name", "default"), "required":cal.get("required", False)}
        if args.operation == "propose":
            proposed = profiles.fit_feedback(cfg)
            return {"message": f"Proposed threshold: {proposed['threshold_db']} dB. Run acoustic apply to save."}
        result = {}
        def mutate(document):
            cal = document.setdefault("calibration", {})
            identity = profiles.device_identity(document)
            op, value = args.operation, args.value
            if op == "device":
                if cal.get("device_key") == identity and not cal.get("required"):
                    profiles.remember(document, identity)
                document.setdefault("audio", {})["device_index"] = None if value == "default" else int(value)
                identity = profiles.device_identity(document)
                found = profiles.select(document, identity, cal.get("active_name", "default"))
                result["message"] = "Loaded matching calibration" if found else "New microphone: calibrate before live actions"
            elif op == "use":
                found = profiles.select(document, identity, value)
                result["message"] = "Loaded desk " + value if found else "New desk " + value + ": calibrate first"
            elif op == "feedback":
                if not args.label or args.db is None:
                    raise ValueError("Feedback requires --label and --db")
                count = profiles.add_feedback(document, args.label, args.db, args.accepted)
                result["message"] = f"Saved feature label ({count} samples). No detection settings changed."
            elif op == "apply":
                threshold = profiles.apply_feedback(document)
                result["message"] = f"Saved {threshold} dB threshold; test in preview and run work-noise audit"
            elif op == "rollback":
                profiles.rollback(document)
                result["message"] = "Restored previous threshold"
            else:
                raise ValueError("Unknown acoustic operation")
        edit_config(path, mutate)
        return result
    finally:
        lock.release()
