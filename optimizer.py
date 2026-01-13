
from itertools import combinations, permutations
from typing import List, Dict, Tuple, Union, Optional, Set
import config

# --- CORE OPTIMIZATION FUNCTIONS ---
def calculate_split_shopping_price(
    shopping_list: List[Dict[str, Union[str, int]]],
    store_ids: List[str], 
    price_database: Dict[str, Dict[str, float]]
) -> Tuple[float, Dict[str, int]]:
    """Calculate minimum total cost and item assignments."""
    total_price = 0.0
    item_assignment_counts: Dict[str, int] = {s: 0 for s in store_ids}
    
    for item_data in shopping_list:
        item = item_data["name"]
        quantity = item_data["qty"]
        min_item_cost = float('inf')
        best_store = None
        
        for store_id in store_ids:
            unit_price = price_database.get(store_id, {}).get(item, float('inf'))
            if unit_price != float('inf'):
                cost = unit_price * quantity
                if cost < min_item_cost:
                    min_item_cost = cost
                    best_store = store_id
        
        if min_item_cost == float('inf'):
            return float('inf'), item_assignment_counts
        
        total_price += min_item_cost
        if best_store:
            item_assignment_counts[best_store] += quantity
    
    return total_price, item_assignment_counts

def find_fastest_travel_permutation(
    store_indices_subset: Tuple[int, ...], 
    durations_matrix: List[List[float]], 
    start_index: int
) -> Tuple[Tuple[int, ...], float]:
    """Find fastest route order for given stores."""
    min_travel_time = float('inf')
    best_route_indices = store_indices_subset
    
    for route_indices in permutations(store_indices_subset):
        travel_time = 0.0
        current_index = start_index
        
        for next_index in route_indices:
            travel_time += durations_matrix[current_index][next_index]
            current_index = next_index
        
        travel_time += durations_matrix[current_index][start_index]
        
        if travel_time < min_travel_time:
            min_travel_time = travel_time
            best_route_indices = route_indices
    
    return best_route_indices, min_travel_time

def find_optimal_store(
    durations_matrix: List[List[float]],
    price_database: Dict[str, Dict[str, float]],
    location_names: List[str],
    shopping_list: List[Dict[str, Union[str, int]]]
) -> Tuple[List[str], float, float]:
    """
    FULL OPTIMIZATION with all pruning phases - WITH DEBUGGING
    """
    start_index = location_names.index("Start")
    optimal_route: List[str] = []
    min_cost = float('inf')
    best_total_time = 0.0
    
    if not shopping_list:
        print("No shopping list items!")
        return [], 0.0, 0.0
    
    print(f"\n=== OPTIMIZATION START ===")
    print(f"Constraint: Total route must be <= {int(config.MAX_TIME_SECONDS/60)} minutes")
    print(f"Number of stores: {len(location_names) - 1}")
    print(f"Number of items: {len(shopping_list)}")
    
    store_indices = list(range(1, len(location_names)))
    
    # Debug: Show store names
    print(f"\nStores available:")
    for idx in store_indices:
        print(f"  {idx}: {location_names[idx]}")
    
    # Set to store subsets that failed time constraint
    failed_time_subsets: Set[frozenset[int]] = set()
    
    k1_winner_store_id: Optional[str] = None
    
    # --- Phase 1: Single Store Baseline ---
    print("\n=== PHASE 1: Single Store Baseline ===")
    
    single_store_costs = {}
    
    for store_indices_subset in combinations(store_indices, 1):
        store_index = store_indices_subset[0]
        store_id = location_names[store_index]
        
        item_cost, item_quantity_counts = calculate_split_shopping_price(
            shopping_list, [store_id], price_database
        )
        
        if item_cost == float('inf'):
            print(f"  {store_id}: Cannot buy all items here")
            continue
        
        single_store_costs[store_id] = item_cost
        
        # Calculate shopping time
        store_type = store_id.split(' ')[0]
        multiplier = config.STORE_TIME_MULTIPLIERS.get(store_type, 1.0)
        quantity = item_quantity_counts.get(store_id, 0)
        shopping_time = (config.BASE_FIXOUT_OVERHEAD * multiplier) + (quantity * config.TIME_PER_UNIT_SECONDS)
        
        # Calculate travel time
        travel_time = durations_matrix[start_index][store_index] + durations_matrix[store_index][start_index]
        total_time = travel_time + shopping_time
        
        if total_time <= config.MAX_TIME_SECONDS:
            if item_cost < min_cost:
                min_cost = item_cost
                optimal_route = [store_id]
                best_total_time = total_time
                k1_winner_store_id = store_id
                print(f"  {store_id}: ✅ NEW BEST! ${item_cost:.2f} | {int(total_time/60)}m")
            else:
                print(f"  {store_id}: ${item_cost:.2f} | {int(total_time/60)}m (worse than ${min_cost:.2f})")
        else:
            print(f"  {store_id}: ❌ Time exceeded ({int(total_time/60)}m > {int(config.MAX_TIME_SECONDS/60)}m)")
    
    if min_cost == float('inf') or k1_winner_store_id is None:
        print("\n❌ No single-stop route meets time constraint.")
        return optimal_route, min_cost, best_total_time
    
    print(f"\n✅ Single store winner: {k1_winner_store_id} at ${min_cost:.2f}")
    
    # --- Phase 2: Store Pruning ---
    print(f"\n=== PHASE 2: Store Pruning ===")
    print(f"Comparing other stores against winner: {k1_winner_store_id}")
    
    eligible_multistop_indices: List[int] = []
    
    # Always include the winner
    winner_index = location_names.index(k1_winner_store_id)
    eligible_multistop_indices.append(winner_index)
    
    for index in store_indices:
        store_id = location_names[index]
        
        if store_id == k1_winner_store_id:
            continue  # Already added
            
        is_store_useful = False
        cheaper_items = []
        
        # Check if this store has ANY item cheaper than the winner
        for item_data in shopping_list:
            item_name = item_data["name"]
            
            winner_price = price_database.get(k1_winner_store_id, {}).get(item_name, float('inf'))
            store_price = price_database.get(store_id, {}).get(item_name, float('inf'))
            
            if store_price < winner_price:
                is_store_useful = True
                cheaper_items.append(f"{item_name}: ${store_price:.2f} vs ${winner_price:.2f}")
                break  # Only need one cheaper item
        
        if is_store_useful:
            eligible_multistop_indices.append(index)
            print(f"  {store_id}: ✅ Kept - has cheaper items")
            if cheaper_items:
                print(f"     e.g., {cheaper_items[0]}")
        else:
            print(f"  {store_id}: 🛑 Pruned - no cheaper items")
    
    print(f"\nEligible stores for multi-stop optimization: {len(eligible_multistop_indices)}")
    for idx in eligible_multistop_indices:
        print(f"  - {location_names[idx]}")
    
    # --- Phase 3: Multi-Store Optimization ---
    print(f"\n=== PHASE 3: Multi-Store Optimization ===")
    
    # If only 1 eligible store (just the winner), skip multi-store
    if len(eligible_multistop_indices) <= 1:
        print("Only 1 eligible store. Single store is optimal.")
        return optimal_route, min_cost, best_total_time
    
    # Try 2, 3, 4-store combinations
    max_k = min(4, len(eligible_multistop_indices))
    
    for k in range(2, max_k + 1):
        print(f"\n--- Testing {k}-store combinations ---")
        
        # Generate all combinations
        combinations_list = list(combinations(eligible_multistop_indices, k))
        print(f"  Testing {len(combinations_list)} combinations of {k} stores")
        
        found_any_feasible = False
        combinations_checked = 0
        combinations_pruned = 0
        
        for store_indices_subset in combinations_list:
            route_store_ids = [location_names[i] for i in store_indices_subset]
            route_str = " -> ".join(route_store_ids)
            
            # Skip if superset of failed combination
            current_set = frozenset(store_indices_subset)
            is_superset_of_failed = any(
                failed_set.issubset(current_set) for failed_set in failed_time_subsets
            )
            
            if is_superset_of_failed:
                combinations_pruned += 1
                continue
            
            # Calculate cost for this combination
            item_cost, item_quantity_counts = calculate_split_shopping_price(
                shopping_list, route_store_ids, price_database
            )
            
            combinations_checked += 1
            
            # Quick cost check - skip if not cheaper
            if item_cost >= min_cost:
                # print(f"    {route_str}: Cost ${item_cost:.2f} not better than ${min_cost:.2f}")
                continue
            
            # Calculate shopping time for all stores
            total_shopping_time = 0.0
            min_one_way_travel = float('inf')
            
            for store_id in route_store_ids:
                store_type = store_id.split(' ')[0]
                multiplier = config.STORE_TIME_MULTIPLIERS.get(store_type, 1.0)
                quantity = item_quantity_counts.get(store_id, 0)
                store_shopping_time = (config.BASE_FIXOUT_OVERHEAD * multiplier) + (quantity * config.TIME_PER_UNIT_SECONDS)
                total_shopping_time += store_shopping_time
                
                # Find minimum travel to any store in this combination
                store_index = location_names.index(store_id)
                travel_to_store = durations_matrix[start_index][store_index]
                if travel_to_store < min_one_way_travel:
                    min_one_way_travel = travel_to_store
            
            # Quick time check (lower bound)
            lower_bound_travel = 2 * min_one_way_travel
            lower_bound_total = lower_bound_travel + total_shopping_time
            
            if lower_bound_total > config.MAX_TIME_SECONDS:
                failed_time_subsets.add(current_set)
                # print(f"    {route_str}: Lower bound time {int(lower_bound_total/60)}m > limit")
                continue
            
            found_any_feasible = True
            
            # Find optimal route order
            best_route_indices, min_travel_time = find_fastest_travel_permutation(
                store_indices_subset, durations_matrix, start_index
            )
            
            total_time = min_travel_time + total_shopping_time
            
            if total_time > config.MAX_TIME_SECONDS:
                failed_time_subsets.add(current_set)
                print(f"    {route_str}: ❌ Time {int(total_time/60)}m > limit {int(config.MAX_TIME_SECONDS/60)}m")
                continue
            
            # New best route found!
            min_cost = item_cost
            optimal_route = [location_names[i] for i in best_route_indices]
            best_total_time = total_time
            
            print(f"    {route_str}: ✅ NEW BEST! Cost: ${item_cost:.2f} | Time: {int(total_time/60)}m")
            
            # Show item assignment breakdown
            print(f"      Item assignments:")
            for item_data in shopping_list:
                item_name = item_data["name"]
                quantity = item_data["qty"]
                best_store_for_item = None
                best_price_for_item = float('inf')
                
                for store_id in route_store_ids:
                    price = price_database.get(store_id, {}).get(item_name, float('inf'))
                    if price < best_price_for_item:
                        best_price_for_item = price
                        best_store_for_item = store_id
                
                if best_store_for_item:
                    print(f"        {quantity}× {item_name}: ${best_price_for_item:.2f} at {best_store_for_item}")
        
        print(f"  Checked: {combinations_checked}, Pruned: {combinations_pruned}")
        
        # If no feasible combinations at this k, continue to next k
        if not found_any_feasible:
            print(f"  No feasible {k}-store combinations")
    
    print(f"\n=== OPTIMIZATION COMPLETE ===")
    return optimal_route, min_cost, best_total_time
