class TransferError(Exception):
    pass


class InsufficientFunds(TransferError):
    pass


class SameAccount(TransferError):
    pass


class InvalidAmount(TransferError):
    pass


class DifferentCurrency(TransferError):
    pass


class ForeignAccount(TransferError):
    pass


class AccountHasOperations(Exception):
    """Стартовый остаток можно указать только у счёта без операций."""
