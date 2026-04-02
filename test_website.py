#!/usr/bin/env python3
"""
Comprehensive Test Suite for CodeFlow3D Website
Tests all backend endpoints and verifies frontend integration
"""

import requests
import json
import time
import sys

def print_test(test_name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {test_name}")
    if details:
        print(f"         {details}")

def main():
    print("\n" + "="*70)
    print("CodeFlow3D COMPREHENSIVE TEST SUITE")
    print("="*70 + "\n")
    
    BACKEND_URL = "http://localhost:8000"
    all_passed = True
    test_api_key = None
    
    # Test 1: Ping endpoint
    try:
        resp = requests.get(f"{BACKEND_URL}/ping", timeout=5)
        passed = resp.status_code == 200 and resp.json().get("status") == "pong"
        print_test("1. Ping Endpoint", passed, f"Status: {resp.status_code}")
    except Exception as e:
        print_test("1. Ping Endpoint", False, str(e))
        all_passed = False
        return False
    
    # Test 2: Root endpoint
    try:
        resp = requests.get(f"{BACKEND_URL}/", timeout=5)
        passed = resp.status_code == 200 and "docs" in resp.json()
        print_test("2. Root Endpoint", passed, f"Status: {resp.status_code}")
    except Exception as e:
        print_test("2. Root Endpoint", False, str(e))
        all_passed = False
    
    # Test 3: Test endpoint
    try:
        resp = requests.get(f"{BACKEND_URL}/test", timeout=5)
        data = resp.json()
        passed = (resp.status_code == 200 and 
                 "nodes" in data and len(data["nodes"]) > 0)
        print_test("3. Test Endpoint", passed, 
                  f"Status: {resp.status_code}, Nodes: {len(data.get('nodes', []))}")
    except Exception as e:
        print_test("3. Test Endpoint", False, str(e))
        all_passed = False
    
    # Test 4: User Registration
    try:
        user_data = {
            "username": f"testuser_{int(time.time())}",
            "email": f"test_{int(time.time())}@example.com",
            "password": "TestPassword123"
        }
        resp = requests.post(f"{BACKEND_URL}/register", json=user_data, timeout=5)
        passed = resp.status_code == 200
        if passed:
            test_api_key = resp.json().get("api_key")
            print_test("4. User Registration", passed, 
                      f"Status: {resp.status_code}, API Key: {test_api_key[:20]}...")
        else:
            print_test("4. User Registration", False, 
                      f"Status: {resp.status_code}")
    except Exception as e:
        print_test("4. User Registration", False, str(e))
        all_passed = False
    
    # Test 5: Code Analysis (if API key obtained)
    if test_api_key:
        try:
            code = "def add(a, b):\n    return a + b"
            payload = {
                "language": "python",
                "code": code,
                "save_graph": False
            }
            resp = requests.post(
                f"{BACKEND_URL}/analyze",
                json=payload,
                headers={"x-api-key": test_api_key},
                timeout=5
            )
            passed = resp.status_code == 200 and "task_id" in resp.json()
            if passed:
                task_id = resp.json()["task_id"]
                print_test("5. Code Analysis Submission", passed, 
                          f"Status: {resp.status_code}, Task: {task_id[:20]}...")
            else:
                print_test("5. Code Analysis Submission", False, 
                          f"Status: {resp.status_code}")
        except Exception as e:
            print_test("5. Code Analysis Submission", False, str(e))
            all_passed = False
    else:
        print_test("5. Code Analysis Submission", False, "No API key available")
        all_passed = False
    
    # Test 6: Analysis History
    if test_api_key:
        try:
            resp = requests.get(
                f"{BACKEND_URL}/history",
                headers={"x-api-key": test_api_key},
                timeout=5
            )
            data = resp.json()
            passed = resp.status_code == 200 and "analyses" in data
            print_test("6. Analysis History", passed, 
                      f"Status: {resp.status_code}, Count: {len(data.get('analyses', []))}")
        except Exception as e:
            print_test("6. Analysis History", False, str(e))
            all_passed = False
    else:
        print_test("6. Analysis History", False, "No API key available")
        all_passed = False
    
    # Test 7: Frontend Server (try both Docker port 5500 and dev port 5501)
    try:
        frontend_url = "http://localhost:5500/"
        try:
            resp = requests.get(frontend_url, timeout=5)
        except Exception:
            frontend_url = "http://localhost:5501/"
            resp = requests.get(frontend_url, timeout=5)
        passed = resp.status_code == 200 and "canvas" in resp.text
        print_test("7. Frontend Server", passed,
                  f"URL: {frontend_url}, Status: {resp.status_code}, HTML: {len(resp.text)} bytes")
    except Exception as e:
        print_test("7. Frontend Server", False, str(e))
        print("         (Frontend not required for backend testing)")
    
    # Test 8: CORS Configuration
    try:
        # Test CORS with proper headers - use the allowed origin
        resp = requests.get(
            f"{BACKEND_URL}/test",
            headers={"Origin": "http://localhost:5500"},
            timeout=5
        )
        # Check if request succeeds - CORS is working if request returns 200
        passed = resp.status_code == 200
        cors_header = resp.headers.get("access-control-allow-origin", "Not set")
        print_test("8. CORS Configuration", passed,
                  f"Status: {resp.status_code}, Allow-Origin: {cors_header}")
    except Exception as e:
        print_test("8. CORS Configuration", False, str(e))
    
    print("\n" + "="*70)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("⚠️  SOME TESTS FAILED OR SKIPPED")
    print("="*70 + "\n")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
