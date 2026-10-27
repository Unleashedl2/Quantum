# Respaldos (esquema propuesto — se implementa y prueba en la Fase 8)
```
pg_dump -Fc -h db -U $POSTGRES_USER $POSTGRES_DB | age -r $BACKUP_PUBLIC_KEY > backup_$(date +%F).dump.age
```
- Programar con cron del host; copia fuera del servidor (S3 con otra credencial).
- Restauración: `age -d -i key.txt backup.dump.age | pg_restore -d quantumstore_restore --clean --if-exists`.
- Un respaldo no probado no cuenta: la Fase 8 incluye una prueba de restauración automatizada.
