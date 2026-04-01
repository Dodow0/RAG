import requests

url = "https://router.tumuer.me/v1/embeddings"

headers = {
    "Authorization": "sk-ySluVBnKghczMMUAXn2cCeJcXCjv8KRFzckMu2ppjQms2ATv",
    "Content-Type": "application/json"
}

data = {
    "model": "Qwen/Qwen3-Embedding-4B",
    "input": "这是一段需要转换成向量的文本",
    "encoding_format": "float"
}

res = requests.post(url, headers=headers, json=data)

print(res.json())