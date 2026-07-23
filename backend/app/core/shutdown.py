import logging
import signal
import threading

logger = logging.getLogger(__name__)

# Global thread-safe event that is set when the application is shutting down.
shutdown_event = threading.Event()

def set_shutdown() -> None:
    """Trigger the global shutdown event."""
    if not shutdown_event.is_set():
        logger.info("Setting global shutdown event")
        shutdown_event.set()

_installed = False

def install_shutdown_handlers() -> None:
    """Install signal handlers to catch SIGINT and SIGTERM and trigger the global shutdown event.
    
    This allows streaming generators and background threads to interrupt blocking I/O/sleep operations.
    """
    global _installed
    if _installed:
        return
    _installed = True

    try:
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        def handler(signum, frame):
            logger.info("Signal %d received; triggering graceful shutdown event", signum)
            set_shutdown()
            
            # Forward the signal to Uvicorn's original handlers
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
        logger.info("Installed custom SIGINT and SIGTERM signal handlers")
    except ValueError as e:
        logger.warning(
            "Could not install signal handlers (expected if not running in the main thread): %s", e
        )
    except Exception:
        logger.exception("Failed to install signal handlers for graceful shutdown")
