#!/bin/bash

# 获取待处理文章ID列表
IDs=($(sqlite3 /srv/LapTalk_NewsAggregationTool/news-web/backend/data/news.db "SELECT id FROM news_articles WHERE content_status='pending_cluster' ORDER BY id DESC LIMIT 50"))
total=${#IDs[@]}
success=0
failed=0
total_time=0
count=0

echo "开始处理 $total 篇 pending_cluster 文章"

for id in "${IDs[@]}"; do
    count=$((count + 1))
    start_time=$(date +%s)
    
    echo "[$count/$total] 处理文章 ID: $id"
    
    # 调用API处理文章
    response=$(curl -s --max-time 120 -X POST "http://localhost:8081/api/pipeline/article/$id/process")
    status_code=$?
    end_time=$(date +%s)
    elapsed=$((end_time - start_time))
    total_time=$((total_time + elapsed))
    
    # 检查响应
    if [ $status_code -ne 0 ]; then
        echo "  错误: 请求失败 (curl退出码: $status_code)"
        failed=$((failed + 1))
    else
        # 检查HTTP状态码
        http_code=$(echo "$response" | grep -o '"status_code":[0-9]*' | cut -d':' -f2 || echo "")
        
        if [[ "$response" == *"success"* ]] || [[ "$http_code" == "200" ]]; then
            echo "  成功: 文章 $id 已处理 (耗时: ${elapsed}秒)"
            success=$((success + 1))
        elif [[ "$response" == *"429"* ]] || [[ "$http_code" == "429" ]]; then
            echo "  警告: 遇到429限流，等待60秒..."
            sleep 60
            # 重试一次
            echo "  重试文章 $id"
            start_retry=$(date +%s)
            retry_response=$(curl -s --max-time 120 -X POST "http://localhost:8081/api/pipeline/article/$id/process")
            end_retry=$(date +%s)
            retry_elapsed=$((end_retry - start_retry))
            total_time=$((total_time + retry_elapsed))
            
            if [[ "$retry_response" == *"success"* ]]; then
                echo "  重试成功 (耗时: ${retry_elapsed}秒)"
                success=$((success + 1))
            else
                echo "  重试失败: $retry_response"
                failed=$((failed + 1))
            fi
        else
            echo "  失败: $response"
            failed=$((failed + 1))
        fi
    fi
    
    # 每10篇汇报一次进度
    if [ $((count % 10)) -eq 0 ]; then
        avg_time=$((total_time / count))
        echo ""
        echo "=== 进度汇报 ==="
        echo "已处理: $count 篇"
        echo "成功: $success 篇"
        echo "失败: $failed 篇"
        echo "平均耗时: ${avg_time}秒/篇"
        echo ""
    fi
done

# 最终汇报
avg_time=$((total_time / total))
echo ""
echo "=========================================="
echo "处理完成!"
echo "总文章数: $total 篇"
echo "成功处理: $success 篇"
echo "失败: $failed 篇"
echo "总耗时: $total_time 秒"
echo "平均耗时: ${avg_time}秒/篇"
echo "=========================================="