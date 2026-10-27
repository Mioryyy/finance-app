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
