-- Run these in MySQL/SQLite after loading the data into a table named orders
SELECT Region, ROUND(SUM(Sales),0) AS sales, ROUND(SUM(Profit),0) AS profit,
       ROUND(SUM(Profit)*100.0/SUM(Sales),1) AS margin_pct
FROM orders GROUP BY Region ORDER BY profit DESC;

SELECT Product_Name, ROUND(SUM(Profit),0) AS total_profit
FROM orders GROUP BY Product_Name HAVING SUM(Profit) < 0 ORDER BY total_profit LIMIT 10;

SELECT * FROM (
  SELECT Category, Product_Name, ROUND(SUM(Profit),0) AS profit,
         RANK() OVER (PARTITION BY Category ORDER BY SUM(Profit) DESC) AS rnk
  FROM orders GROUP BY Category, Product_Name) t WHERE rnk = 1;
