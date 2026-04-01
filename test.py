def get_req(count_a: int, count_b: int) -> dict:
    if count_a >= count_b:
        host, guest = count_a, count_b
        a_is_host = True
    else:
        host, guest = count_b, count_a
        a_is_host = False

    REF = 2300
    scale = host / REF

    tiers = [
        (round(400 * scale), "none", "member"),
        (round(800 * scale), "partner", "member"),
        (round(1700 * scale), "here", "member"),
        (round(2000 * scale), "partnerhere", "member"),
        (float("inf"), "member", "member")
    ]

    for ceiling, host_ping, guest_ping in tiers:
        if guest <= ceiling:
            if a_is_host:
                ping_a, ping_b = host_ping, guest_ping
            else:
                ping_a, ping_b = guest_ping, host_ping

            return {
                "server_a": ping_a,
                "server_b": ping_b,
                "host": "server_a" if a_is_host else "server_b",
            }
        
SERVER_A = 650
SERVER_B = 2200

r = get_req(SERVER_A, SERVER_B)
print(f"{r['server_a']}\n{r['server_b']}\n{r['host']}")