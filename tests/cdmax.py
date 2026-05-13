def will_keepup(cd: int, server_amount: int = 50):
    print(f"Partners needed: {72 / cd}, Partners available: {server_amount}")
    if cd == 0:
        return False
    return (72 / cd) <= server_amount

print(will_keepup(2, 70))