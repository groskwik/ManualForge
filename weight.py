#!/usr/bin/env python

while True:
    try:
        P = float(input("Number of pages: "))
    except ValueError:
        print("Please enter a valid number.")
        continue

    A = 0.082
    O = P * A

    E = 1
    if P > 200:
        E = 1.6

    O = O + E

    L1 = int(O // 16)   # pounds
    L2 = int(O % 16)    # ounces

    if L1 == 0:
        print(f"Weight: {L2} oz")
    else:
        print(f"Weight: {L1} lb {L2} oz")
