"""Quick smoke tests for evaluate_vm_rightsizing."""
import sys, json, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_servers"))

import finops_cross_examine_server as srv

def run(label, metrics_json, method="point_in_time"):
    result = json.loads(srv.evaluate_vm_rightsizing(metrics_json, method))
    vm = result["results"][0]
    f = vm["findings"][0]
    print(f"\n=== {label} ===")
    print(f"  Family: {vm['family']}")
    print(f"  Severity: {f['rule_severity']} | Action: {f['action']}")
    if f.get("target_family"):
        print(f"  Target: {f['target_family']} → Azure: {f.get('target_azure_series',[])} | AWS: {f.get('target_aws_equivalent','')} | GCP: {f.get('target_gcp_equivalent','')}")
    if f.get("estimated_monthly_savings"):
        print(f"  Est savings: ${f['estimated_monthly_savings']}")
    print(f"  Total savings: ${result['total_potential_monthly_savings']}")
    return result

# Test 1: Idle D-Series (CPU 1.2%) → critical, delete
run("T1: Idle D-Series CPU=1.2%",
    json.dumps([{"resource_name":"vm-idle-01","series":"D-Series","metric_name":"Percent CPU","metric_value":1.2,"monthly_cost":350}]))

# Test 2: Underutilized F-Series (CPU 15%) → should suggest D-Series
run("T2: F-Series underutil CPU=15%",
    json.dumps([{"resource_name":"vm-compute-01","series":"F-Series","metric_name":"Percent CPU","metric_value":15,"monthly_cost":600}]))

# Test 3: B-Series sustained high CPU (88%) → upgrade to D-Series
run("T3: B-Series high CPU=88%",
    json.dumps([{"resource_name":"vm-burst-01","series":"B-Series","metric_name":"Percent CPU","metric_value":88,"monthly_cost":120}]))

# Test 4: P95 method — Dsv4 oversized (CPU 12%)
run("T4: P95 Dsv4 oversized CPU=12%",
    json.dumps([{"resource_name":"vm-web-03","series":"Dsv4 Series","metric_name":"Percent CPU","metric_value":12,"monthly_cost":800}]),
    method="p95_30day")

# Test 5: Well-sized D-Series (CPU 45%) → optimized
run("T5: Well-sized D-Series CPU=45%",
    json.dumps([{"resource_name":"vm-prod-01","series":"D-Series","metric_name":"Percent CPU","metric_value":45,"monthly_cost":500}]),
    method="p95_30day")

# Test 6: Multiple VMs — sort order
multi = json.dumps([
    {"resource_name":"vm-ok","series":"D-Series","metric_name":"Percent CPU","metric_value":50,"monthly_cost":200},
    {"resource_name":"vm-critical","series":"E-Series","metric_name":"Percent CPU","metric_value":0.5,"monthly_cost":1200},
    {"resource_name":"vm-oversized","series":"D-Series","metric_name":"Percent CPU","metric_value":8,"monthly_cost":900},
])
r6 = json.loads(srv.evaluate_vm_rightsizing(multi, "point_in_time"))
print("\n=== T6: Multi-VM sort ===")
for r in r6["results"]:
    print(f"  {r['resource_name']}: {r['findings'][0]['rule_severity']} / {r['findings'][0]['action']} (${r['monthly_cost']})")
print(f"  Total savings: ${r6['total_potential_monthly_savings']}")
print(f"  VMs with findings: {r6['vms_with_findings']} / {r6['total_vms_evaluated']}")

# Test 7: Idle GPU NC-Series (CPU 3%) → critical, delete/resize to D
run("T7: Idle GPU NC-Series CPU=3%",
    json.dumps([{"resource_name":"vm-gpu-01","series":"NC-Series","metric_name":"Percent CPU","metric_value":3,"monthly_cost":2500}]))

# Test 8: E-Series stressed (CPU 92%) → warning, upsize
run("T8: E-Series stressed CPU=92%",
    json.dumps([{"resource_name":"vm-mem-01","series":"E-Series","metric_name":"Percent CPU","metric_value":92,"monthly_cost":700}]))

# Test 9: Invalid input
r9 = json.loads(srv.evaluate_vm_rightsizing("not json", "p95_30day"))
print(f"\n=== T9: Invalid input → {r9.get('error','no error?')} ===")

# Test 10: Unknown method
r10 = json.loads(srv.evaluate_vm_rightsizing(json.dumps([{"resource_name":"x","series":"D","metric_name":"Percent CPU","metric_value":50,"monthly_cost":100}]), "bad_method"))
print(f"=== T10: Unknown method → {r10.get('error','no error?')} ===")

print("\n✓ ALL TESTS COMPLETE")
