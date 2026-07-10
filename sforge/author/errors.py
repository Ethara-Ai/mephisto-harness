from __future__ import annotations


class AuthorError(Exception):
    exit_code: int = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ManifestError(AuthorError):
    exit_code = 1


class CloneError(AuthorError):
    exit_code = 2


class GutError(AuthorError):
    exit_code = 2


class ContaminationError(AuthorError):
    exit_code = 3


class CalibrationError(AuthorError):
    exit_code = 4


class TierMismatchError(AuthorError):
    exit_code = 5
