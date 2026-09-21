target_count = 17
TRAY_CAPACITY = 8
for piece in range(1, target_count + 1):
        print(piece)
        if TRAY_CAPACITY and piece > 1 and (piece - 1) % TRAY_CAPACITY == 0:
                print("ask tray")