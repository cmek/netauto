class NetAutoException(Exception):
    def __init__(self, error_info):
        self.error_info = error_info
        super().__init__(error_info)
