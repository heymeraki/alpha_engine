import json
import os
from datetime import datetime, timedelta

class SubmitManager:
    """管理优质因子提交的类"""
    
    def __init__(self, db_file='records/submitted_alphas.json'):
        self.db_file = db_file
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """确保数据文件存在"""
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        if not os.path.exists(self.db_file):
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
    
    def _load_data(self):
        """加载提交记录"""
        try:
            with open(self.db_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    
    def _save_data(self, data):
        """保存提交记录"""
        with open(self.db_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_today_submissions_count(self, user_id):
        """获取今天已提交的数量"""
        data = self._load_data()
        today_str = datetime.now().strftime('%Y-%m-%d')
        count = sum(1 for item in data if item.get('user_id') == user_id and item.get('submit_date') == today_str)
        return count
    
    def can_submit_today(self, user_id):
        """检查今天是否还可以提交"""
        count = self.get_today_submissions_count(user_id)
        return count < 4
    
    def submit_alpha(self, user_id, alpha_id, alpha_data):
        """
        提交一个优质因子
        
        参数:
            user_id: 用户ID
            alpha_id: 因子ID
            alpha_data: 因子详细信息（dict）
        
        返回:
            (success: bool, message: str)
        """
        if not self.can_submit_today(user_id):
            return (False, '今日已提交4个因子，已达上限')
        
        sharpe = alpha_data.get('sharpe', 0)
        if sharpe < 1:
            return (False, f'因子Sharpe={sharpe:.4f}，未达到1.00的最低要求')
        
        data = self._load_data()
        for item in data:
            if item.get('alpha_id') == alpha_id and item.get('user_id') == user_id:
                return (False, '该因子已经提交过')
        
        submit_record = {
            'user_id': user_id,
            'alpha_id': alpha_id,
            'submit_date': datetime.now().strftime('%Y-%m-%d'),
            'submit_time': datetime.now().isoformat(),
            'sharpe': sharpe,
            'fitness': alpha_data.get('fitness', 0),
            'turnover': alpha_data.get('turnover', 0),
            'returns': alpha_data.get('returns', 0),
            'longCount': alpha_data.get('longCount', 0),
            'shortCount': alpha_data.get('shortCount', 0),
            'region': alpha_data.get('region', ''),
            'universe': alpha_data.get('universe', ''),
            'delay': alpha_data.get('delay', 0)
        }
        data.append(submit_record)
        self._save_data(data)
        return (True, '提交成功！')
    
    def get_user_submissions(self, user_id, days=30):
        """获取用户最近的提交记录"""
        data = self._load_data()
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        user_submissions = [
            item for item in data
            if item.get('user_id') == user_id and item.get('submit_date', '') >= cutoff_date
        ]
        user_submissions.sort(key=lambda x: x.get('submit_time', ''), reverse=True)
        return user_submissions
    
    def get_submission_stats(self, user_id):
        """获取用户的提交统计信息"""
        data = self._load_data()
        user_submissions = [item for item in data if item.get('user_id') == user_id]
        if not user_submissions:
            return {
                'total_count': 0,
                'avg_sharpe': 0,
                'best_sharpe': 0,
                'today_count': 0,
                'remaining_today': 4
            }
        
        today_count = self.get_today_submissions_count(user_id)
        sharpes = [item.get('sharpe', 0) for item in user_submissions]
        
        return {
            'total_count': len(user_submissions),
            'avg_sharpe': sum(sharpes) / len(sharpes) if sharpes else 0,
            'best_sharpe': max(sharpes) if sharpes else 0,
            'today_count': today_count,
            'remaining_today': 4 - today_count
        }

submit_manager = SubmitManager()