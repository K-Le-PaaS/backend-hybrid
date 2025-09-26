#!/usr/bin/env python3
import requests


def main():
    base_url = "http://localhost:8000"
    resp = requests.get(f"{base_url}/api/v1/health")
    print("health:", resp.status_code)


if __name__ == "__main__":
    main()

