class TransferError(Exception):
    pass
class InsufficientFunds(TransferError):
    pass
class IdentacalAccounts(TransferError):
    pass
class UncorrectAmount(TransferError):
    pass
class DifferentCurrency(TransferError):
    pass
class ElsesAccount(TransferError):
    pass