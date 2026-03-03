import numpy as np
import random

random.seed(42)
np.random.seed(42)

data_url = "https://example.com/data/sample.csv"

def process():
    data = np.random.randn(100, 10)
    return data.mean(axis=0)

if __name__ == "__main__":
    result = process()
    print(result)
