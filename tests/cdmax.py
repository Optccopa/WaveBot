def will_keepup(cd: int, server_amount: int = 70):
    print(f"Partners needed: {168 / cd}, Partners available: {server_amount}")
    if cd == 0:
        return False
    return (168 / cd) <= server_amount

print(will_keepup(2, 70))