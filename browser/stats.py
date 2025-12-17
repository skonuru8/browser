"""
stats.py
Visualization module for the browser using Matplotlib and Pandas.
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
from urllib.parse import urlparse


def show_history_stats(history_file: str = "browser_history.csv") -> None:
    """
    Reads the browser history CSV using Pandas and displays a
    bar chart of the top visited domains using Matplotlib.
    """
    if not os.path.exists(history_file):
        print("No history file found. Browse some pages first!")
        return

    try:
        df = pd.read_csv(history_file)

        if df.empty or "url" not in df.columns:
            print("History is empty or invalid.")
            return

        def get_domain(url_str: str) -> str:
            try:
                url_str = str(url_str)
                if "://" not in url_str:
                    url_str = "http://" + url_str
                return urlparse(url_str).netloc or "unknown"
            except Exception:
                return "unknown"

        df["domain"] = df["url"].apply(get_domain)

        domain_counts = df["domain"].value_counts()

        plt.figure(figsize=(10, 6))
        domain_counts.head(10).plot(kind="bar")
        plt.title("Top Visited Domains")
        plt.xlabel("Domain")
        plt.ylabel("Number of Visits")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.show()

    except Exception as e:
        print(f"Error visualizing stats: {e}")


if __name__ == "__main__":
    show_history_stats()
