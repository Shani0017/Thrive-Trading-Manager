import tkinter as tk
import MetaTrader5 as mt5

from gui import TradeManagerApp


def main():
    root = tk.Tk()
    root.geometry("820x420")
    TradeManagerApp(root, mt5)
    root.mainloop()


if __name__ == "__main__":
    main()
