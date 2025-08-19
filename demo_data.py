from datetime import date, timedelta
import random

def get_demo_data(data_type):
    """Generate demo data for different endpoints"""
    
    if data_type == 'tips':
        # Generate demo tip entries for the last 30 days
        demo_tips = []
        for i in range(30):
            work_date = date.today() - timedelta(days=i)
            cash_tips = round(random.uniform(20, 120), 2)
            card_tips = round(random.uniform(30, 200), 2)
            hours_worked = round(random.uniform(4, 10), 2)
            total_tips = cash_tips + card_tips
            tips_per_hour = round(total_tips / hours_worked, 2)
            sales_amount = round(random.uniform(200, 1000), 2)
            tip_percentage = round(total_tips / sales_amount * 100, 2)
            section = random.choice(['cocktail', 'server 4', 'patio', 'bar'])

            demo_tips.append({
                'id': i + 1,
                'user_id': 'demo-user',
                'cash_tips': cash_tips,
                'card_tips': card_tips,
                'hours_worked': hours_worked,
                'section': section,
                'sales_amount': sales_amount,
                'work_date': work_date.isoformat(),
                'weekday': work_date.weekday(),
                'total_tips': total_tips,
                'tips_per_hour': tips_per_hour,
                'tip_percentage': tip_percentage,
                'comments': random.choice(['Busy night', 'Slow shift', 'Great tips', '']),
                'created_at': f"{work_date}T18:00:00Z",
                'updated_at': f"{work_date}T18:00:00Z"
            })
        
        return {'tips': demo_tips}
    
    elif data_type == 'daily_stats':
        # Generate daily stats for the last 30 days
        daily_stats = []
        for i in range(30):
            work_date = date.today() - timedelta(days=i)
            total_cash = round(random.uniform(40, 180), 2)
            total_card = round(random.uniform(60, 300), 2)
            total_tips = total_cash + total_card
            total_hours = round(random.uniform(6, 12), 2)
            avg_tips_per_hour = round(total_tips / total_hours, 2)
            total_sales = round(random.uniform(400, 1600), 2)
            avg_tip_percentage = round(total_tips / total_sales * 100, 2)

            daily_stats.append({
                'date': work_date.isoformat(),
                'total_cash': total_cash,
                'total_card': total_card,
                'total_tips': total_tips,
                'total_hours': total_hours,
                'avg_tips_per_hour': avg_tips_per_hour,
                'total_sales': total_sales,
                'avg_tip_percentage': avg_tip_percentage
            })
        
        return {'daily_stats': daily_stats}
    
    elif data_type == 'weekday_stats':
        # Generate weekday averages
        weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekday_stats = []
        
        for i, name in enumerate(weekday_names):
            # Weekend days typically have higher tips
            multiplier = 1.5 if i >= 5 else 1.0
            avg_cash = round(random.uniform(30, 80) * multiplier, 2)
            avg_card = round(random.uniform(50, 150) * multiplier, 2)
            avg_tips = avg_cash + avg_card
            avg_hours = round(random.uniform(5, 9), 2)
            avg_tips_per_hour = round(avg_tips / avg_hours, 2)
            avg_sales = round(random.uniform(500, 1800) * multiplier, 2)
            avg_tip_percentage = round(avg_tips / avg_sales * 100, 2)

            weekday_stats.append({
                'weekday': i,
                'weekday_name': name,
                'avg_cash': avg_cash,
                'avg_card': avg_card,
                'avg_tips': avg_tips,
                'avg_hours': avg_hours,
                'avg_tips_per_hour': avg_tips_per_hour,
                'avg_sales': avg_sales,
                'avg_tip_percentage': avg_tip_percentage
            })
        
        return {'weekday_stats': weekday_stats}
    
    elif data_type == 'breakdown_stats':
        # Generate cash vs card breakdown
        total_cash = round(random.uniform(800, 1500), 2)
        total_card = round(random.uniform(1200, 2500), 2)
        total_tips = total_cash + total_card
        total_sales = round(random.uniform(8000, 15000), 2)
        tip_percentage = round(total_tips / total_sales * 100, 2)

        return {
            'breakdown': {
                'cash_tips': total_cash,
                'card_tips': total_card,
                'total_tips': total_tips,
                'cash_percentage': round((total_cash / total_tips * 100), 1),
                'card_percentage': round((total_card / total_tips * 100), 1),
                'total_sales': total_sales,
                'tip_percentage': tip_percentage
            }
        }

    elif data_type == 'section_stats':
        sections = ['cocktail', 'server 4', 'patio', 'bar']
        section_stats = []
        for sec in sections:
            section_stats.append({
                'section': sec,
                'avg_tips': round(random.uniform(50, 150), 2)
            })
        return {'section_stats': section_stats}

    return {}
