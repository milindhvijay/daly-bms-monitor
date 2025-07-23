import logging

def get_logger(verbose=False):
    """Create a logger with the specified verbosity level."""
    logger = logging.getLogger("daly_bms")
    if verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


class FuturesPool:
    """Simple futures pool implementation."""
    def __init__(self):
        self.futures = []

    def add(self, future):
        self.futures.append(future)
    
    def clear(self):
        """Cancel all pending futures."""
        for future in self.futures:
            if not future.done():
                future.cancel()
        self.futures.clear()
