-- Ejecutar en Neon > SQL Editor DESPUES de desplegar la API y enviar muestras.
-- La API crea la tabla automaticamente. No hay que importar ningun CSV.

SELECT COUNT(*) AS muestras_guardadas, COUNT(DISTINCT robot_id) AS robots
FROM telemetry;

SELECT id, robot_id, timestamp, battery, motor_temp, predicted_status, confidence, model_version
FROM telemetry
ORDER BY id DESC
LIMIT 20;

SELECT robot_id, COUNT(*) AS muestras
FROM telemetry
GROUP BY robot_id
ORDER BY robot_id;

-- probar_conexion.py imprime una consulta con el CHK-... real generado por tu prueba.
-- Usa esa consulta para comparar los mismos IDs que devolvio POST /telemetry.
